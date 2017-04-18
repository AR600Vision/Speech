# Библиотеки распознавания и синтеза речи
import speech_recognition as sr
from gtts import gTTS

# TODO
# make corpus in lower case
# ROS node чтобы получать запросы от ноды распознавания препятствий и других интересностях

# Воспроизведение речи
import pygame
from pygame import mixer
mixer.init()

import os
import sys
import time
import socket
import select

#Threads
import threading


# Библиотека Chatterbot для простого лингвистического ИИ
# https://github.com/gunthercox/ChatterBot
from chatterbot import ChatBot
from chatterbot.trainers import ChatterBotCorpusTrainer

import logging

# Statement from SpeechRecognition.recognize_google()
class Statement:
    def __init__(self, dict):
        self.confidence = dict['confidence']
        self.text = dict['transcript'].lower()

    def __repr__(self):
        return "[{}] {}".format(self.confidence, self.text)

    def __str__(self):
        return self.text

    def __gt__(self, other):
        return self.confidence > other.confidence


class Speech_AI:
    def __init__(self, server_ip, command_port, text_port, google_treshold = 0.5, chatterbot_treshold = 0.45):
        self._recognizer = sr.Recognizer()
        #self._recognizer.energy_threshold = 4000
        self._microphone = sr.Microphone()

        self.google_treshold = google_treshold          # minimial allowed confidence in speech recognition
        self.chatterbot_treshold = chatterbot_treshold  # ---/--- in chatterbot

	# Talking from socket
        self.isTalking = False
        self.isTalkingLock = threading.Lock()
        self.ignoreNext = False
        self.talkingQueue = []

        is_need_train = not self.is_db_exists()
        self.bot = ChatBot(name="Robby",
            logic_adapters=[{
                                'import_path' : 'chatterbot.logic.BestMatch'
                            },
                            {
                                'import_path': 'chatterbot.logic.MathematicalEvaluation',
                                'math_words_language' : 'russian'
                            },
                            {
                                'import_path': 'chatterbot.logic.LowConfidenceAdapter',
                                'threshold': self.chatterbot_treshold,
                                'default_response': 'Как интересно. А расскажешь еще что-нибудь?'
                            }],
            storage_adapter="chatterbot.storage.JsonFileStorageAdapter",
            filters=["chatterbot.filters.RepetitiveResponseFilter"],
            database="./database.json"
        )

        if is_need_train:
            print("Производится обучение на corpus данных")
            self.train()

        self._mp3_name = "speech.mp3"
        self.create_sockets(server_ip, command_port, text_port)

        self.be_quiet = False



    def create_sockets(self, server_ip, command_port, text_port):
        # Commands socket (to send command to FRUND)
        self.server_ip = server_ip
        self.server_port = command_port
        self.server = (self.server_ip, self.server_port)
        self.command_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)


        # Text socket (to say text from FRUND)
        self.my_ip = '0.0.0.0'
        self.my_port = text_port
        self.me = (self.my_ip, self.my_port)
        self.text_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.text_socket.bind(self.me)

        #self.text_socket.setblocking(0)
        #self.wait_text_timeout = 0.1

        # start receiving thread
        t1 = threading.Thread(target=self.socket_receive_thread)
        t1.start()

    def close_sockets(self):
        self.command_sock.close()
        self.text_socket.close()

    # Set IsTalking with thread-safe
    def setIsTalking(self, value):
        self.isTalkingLock.acquire()
        self.isTalking = value
        self.isTalkingLock.release()

    # Get IsTalking with thread-safe
    def getIsTalking(self):
        self.isTalkingLock.acquire()
        value = self.isTalking
        self.isTalkingLock.release()
        return value

    # Listen socket and talking
    def socket_receive_thread(self):
        while(True):

            if self.getIsTalking():
                continue

            while len(self.talkingQueue)>0:
                text = self.talkingQueue.pop(0)
                print('[TextSocket]: From queue')
                print('[TextSocket]: {}'.format(text))
                self.say(text)
                self.ignoreNext = True
                

            print('[TextSocket] Попытка приема текста...')
            ready = select.select([self.text_socket], [], [])
            if ready[0]:
                print("[TextSocket] Текст принят")
                data, addr = self.text_socket.recvfrom(4096)
                text_to_speak = data.decode("utf-8")
                print('[TextSocket]: {}'.format(text_to_speak))

                if not self.getIsTalking():
                    self.ignoreNext = True
                    self.say(text_to_speak)
                else:
                    print('[TextSocket]: already talking') 
                    self.talkingQueue.append(text_to_speak)

            time.sleep(0.5)


    def work(self):
        print('Минутку тишины, пожалуйста...')
        with self._microphone as source:
            self._recognizer.adjust_for_ambient_noise(source)
        # self._recognizer.energy_threshold = 8000
        # self._recognizer.dynamic_energy_threshold = True

        while True:            
            print('Скажи что - нибудь!')

            with self._microphone as source:
                audio = self._recognizer.listen(source)

            if self.ignoreNext:
                self.ignoreNext = False
                continue

            print("Понял, идет распознавание...")
            statements = self.recognize(audio)
            print('Выражения ', statements)
            best_statement = self.choose_best_statement(statements)
            print('Вы сказали: ', best_statement)
            result = self.process_statement(best_statement, statements)

            # I hate 'Sorry, I hear you bad'
            if result=='':
                continue

            print(self.bot.name, " ответил: ", result)

            if not self.be_quiet:
                self.setIsTalking(True)
                self.say(str(result))
                self.setIsTalking(False)
                #self.isTalkingEvent.set()
                

            print()

    # recognize google can return if show_all is True
    # [{'transcript' : 'asdad', 'confidence' : 0.5}, ...] or [{'transcript': 0.5},...] or empty array
    # todo add timeout for request and better error escaping
    def recognize(self, audio):
        statements = []
        # import stopit
        try:
            json = self._recognizer.recognize_google(audio, language="ru_RU", show_all=True)
            statements = self.json_to_statements(json)
        except sr.UnknownValueError:
            print("[GoogleSR] Неизвестное выражение")
        except sr.RequestError as e:
            print("[GoogleSR] Не могу получить данные; {0}".format(e))
        return statements

    # json to statements
    def json_to_statements(self, json):
        statements = []
        if len(json) is not 0:
            for dict in json['alternative']:
                if 'confidence' not in dict:
                    dict['confidence'] = self.google_treshold + 0.1  # must not be filtered
                statements.append(Statement(dict))
        return statements

    # choose best statement from full recognition answer from recognize() method
    def choose_best_statement(self, statements):
        if statements:
            return max(statements, key=lambda s: s.confidence)
        else:
            return None

    def check_in_string(self, string, words):
        if any(word in string for word in words):
            return True
        return False

    def send_command(self, command):
        #self.command_sock.sendto(str(command).encode(), self.server)
        self.command_sock.sendto(bytes([command]), self.server)

    # A lot of cool possibilities can be impemented here (IoT, CV, ...)
    def process_statement(self, best_statement, statements):
        if best_statement is None or best_statement.confidence < self.google_treshold:
            answer = '' #"Простите, вас плохо слышно"
        else:
            command_recognized = False
            for st in statements:
                if self.check_in_string(st.text, ('вперёд', 'иди', 'шагай')):
                    self.send_command(1)
                    answer = "Я знаю эту команду!"
                    command_recognized = True
                elif self.check_in_string(st.text, ('остановись', 'стоп', 'стой')):
                    self.send_command(2)
                    answer = "Я знаю эту команду!"
                    command_recognized = True
                elif self.check_in_string(st.text, ('тихо', 'молчать', 'тишина', 'тише')):
                    self.be_quiet = True
                    command_recognized = True
                    answer = "Я буду вести себя тише"
                elif self.check_in_string(st.text, ('говори', 'громче')):
                    self.be_quiet = False
                    answer = "Я буду говорить громче"
                    command_recognized = True
            if not command_recognized:
                answer = self.make_answer(best_statement.text)  # takes many time to be executed
        return answer

    # Get synthesized mp3 and play it with pygame
    def say(self, phrase):
        # Synthesize answer
        # todo check exceptons there
        print("[GoogleTTS] Начало запроса")
        try:
            tts = gTTS(text=phrase, lang="ru")
            tts.save(self._mp3_name)
        except Exception as e:
            print("[GoogleTTS] Не удалось синтезировать речь: {}".format(e.strerror))
            return
        # Play answer
        mixer.music.load(self._mp3_name)
        mixer.music.play()

        while pygame.mixer.music.get_busy():
            time.sleep(0.1)

    def make_answer(self, statement):
        return self.bot.get_response(statement)

    # train chatterbot with our corpus (all files if ./corpus folder)
    def train(self):
        self.bot.set_trainer(ChatterBotCorpusTrainer)
        self.bot.train("corpus")
        print("Обучение завершено")

    # keyboard exception handler
    def shutdown(self, export=False):
        if export:
            self.bot.trainer.export_for_training('corpus/last_session_corpus.json')
            print("База данных экспортирована в корпус last_session_corpus.json")

        # self._clean_up()
        print("Завершение работы")
        self.close_sockets()
        print("Sockets are closed")

    def clean_up(self):
        os.remove(self._mp3_name)

    # if we have db already we don't need to train bot again
    def is_db_exists(self):
        db_path = os.getcwd() + '/database.json'
        return os.path.isfile(db_path)


def main():
    ai = Speech_AI(server_ip="192.169.1.1", command_port=5005, text_port=5004) #5004
    try:
        ai.work()
    except KeyboardInterrupt:
        ai.shutdown()

main()

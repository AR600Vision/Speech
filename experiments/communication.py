import select
import socket

# for communication with FRUND
server_ip = "192.168.1.10"
server_port = 5005
server = (server_ip, server_port)
command_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
command_sock.sendto("Lets play zelda!".encode(), server)

# to recv messages from AR600_Shell
my_ip = "192.168.1.44"
my_port = 5004
me = (my_ip, my_port)
text_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
text_socket.bind(me)
text_socket.setblocking(0)

while True:
    ready = select.select([text_socket], [], [], 1)
    if ready[0]:
        print("Текст принят")
        text_to_speak, addr = text_socket.recvfrom(4096)
        print(text_to_speak.decode('utf-8'))

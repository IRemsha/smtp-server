import base64
import datetime
import json
import socket
import string
import sys


class SMTPServerInterface:

    def __init__(self):
        self.fr = ''
        self.to = ''
        self.body = ''

    def helo(self, args):
        return None

    def auth(self, args):
        return None

    def mail_from(self, args):
        self.fr = args.replace('\r\n', '').replace('MAIL FROM:', '')
        return None

    def rcpt_to(self, args):
        self.to = args.replace('\r\n', '').replace('RCPT TO:', '')
        return None

    def data(self, args):
        self.body = args
        return None

    # write mail to file, filename - microtime, data - json serialized
    def quit(self, args):
        f = open(str(microtime(datetime.datetime.now())) + '.json.pymail', 'w')
        f.write(json.dumps({'from': self.fr, 'to': self.to, 'body': self.body}, separators=(',', ':')))
        f.close()
        return None

    def reset(self, args):
        return None


#
# Some helper functions for manipulating from & to addresses etc.
#
def microtime(dt):
    unixtime = dt - datetime.datetime(1970, 1, 1)
    return unixtime.days * 24 * 60 * 60 + unixtime.seconds + unixtime.microseconds / 1000000.0


def stripAddress(address):
    """
    Strip the leading & trailing <> from an address.  Handy for
    getting FROM: addresses.
    """
    start = string.index(address, '<') + 1
    end = string.index(address, '>')
    return address[start:end]


def splitTo(address):
    """
    Return 'address' as undressed (host, fulladdress) tuple.
    Handy for use with TO: addresses.
    """
    start = string.index(address, '<') + 1
    sep = string.index(address, '@') + 1
    end = string.index(address, '>')
    return (address[sep:end], address[start:end],)


#
# A specialization of SMTPServerInterface for debug, that just prints its args.
#
class SMTPServerInterfaceDebug(SMTPServerInterface):
    """
    A debug instance of a SMTPServerInterface that just prints its
    args and returns.
    """

    def helo(self, args):
        print()
        'Received "helo"', args.replace('\n', '')
        print('Successful')
        SMTPServerInterface.helo(self, args)

    def auth(self, args):
        print()
        'Received "AUTH LOGIN:"', args.replace('\n', '')
        SMTPServerInterface.auth(self, args)

    def mail_from(self, args):
        print(args)
        'Received "MAIL FROM:"', args.replace('\n', '')
        SMTPServerInterface.mail_from(self, args)

    def rcpt_to(self, args):
        SMTPServerInterface.rcpt_to(self, args)
        print()
        'Received "RCPT TO"', args.replace('\n', '')

    def data(self, args):
        SMTPServerInterface.data(self, args)
        print()
        'Received "DATA", skipped'

    def quit(self, args):
        SMTPServerInterface.quit(self, args)
        print()
        'Received "QUIT"', args.replace('\n', '')

    def reset(self, args):
        SMTPServerInterface.reset(self, args)
        print()
        'Received "RSET"', args.replace('\n', '')


class SMTPServerEngine:

    ST_INIT = 0
    ST_HELO = 1
    ST_MAIL = 2
    ST_RCPT = 3
    ST_DATA = 4
    ST_QUIT = 5
    ST_LOGIN = 6

    def __init__(self, socket, impl):
        self.impl = impl
        self.socket = socket
        self.state = SMTPServerEngine.ST_INIT
        self.login = ''
        self.password = ''
        self.local_host = 'ir.com'
        self.defoult_smtp = ''

    def chug(self):

        self.socket.send(b'220 Welcome\n')
        while 1:
            data = ''
            complete_line = 0

            while not complete_line:
                part = self.socket.recv(1024)
                part = part.decode()
                if len(part):
                    data += part
                    if len(data) >= 2:
                        complete_line = 1
                        if self.state == SMTPServerEngine.ST_LOGIN:
                            try:
                                if not self.login:
                                    self.login = base64.b64decode(data.encode()).decode()
                                elif not self.password:
                                    self.password = base64.b64decode(data.encode()).decode()
                                elif self.login and self.password:
                                    self.detect_host(self.login)
                                    if self.defoult_smtp:
                                        self.send()
                            except Exception as ex:
                                print('Ошибка: {}'.format(ex))
                        if self.state != SMTPServerEngine.ST_DATA:
                            rsp, keep = self.do_command(data)
                            print(rsp, keep, sep='!')
                        else:
                            rsp = self.do_data(data)
                            if rsp is None:
                                continue
                        self.socket.send(rsp + b"\n")
                        if keep == 0:
                            self.socket.close()
                            return
                else:
                    # EOF
                    return
        return

    def do_command(self, data):
        cmd = data[0:4]
        cmd = cmd.upper()
        keep = 1
        rv = None
        if cmd == 'HELO' or cmd == 'EHLO':
            print('EHLO')
            self.state = SMTPServerEngine.ST_HELO
            rv = self.impl.helo(data)
        elif cmd == 'AUTH':
            print('AUTH')
            rv = self.impl.auth(data)
            self.state = SMTPServerEngine.ST_LOGIN

        elif cmd == "RSET":
            rv = self.impl.reset(data)
            self.dataAccum = ""
            self.state = SMTPServerEngine.ST_INIT
        elif cmd == "NOOP":
            pass
        elif cmd == "QUIT":
            rv = self.impl.quit(data)
            keep = 0
        elif cmd == "MAIL":
            if self.state != SMTPServerEngine.ST_LOGIN:
                return (b"503 Bad command sequence", 1)
            self.state = SMTPServerEngine.ST_MAIL
            rv = self.impl.mail_from(data)
        elif cmd == "RCPT":
            if (self.state != SMTPServerEngine.ST_MAIL) and (self.state != SMTPServerEngine.ST_RCPT):
                return (b"503 Bad command sequence", 1)
            self.state = SMTPServerEngine.ST_RCPT
            rv = self.impl.rcpt_to(data)
        elif cmd == "DATA":
            print('DATa')
            if self.state != SMTPServerEngine.ST_RCPT:
                return (b"503 Bad command sequence", 1)
            self.state = SMTPServerEngine.ST_DATA
            self.dataAccum = ""
            return (b"354 OK, Enter data, terminated with a \\r\\n.\\r\\n", 1)
        else:
            return (b"505 Eh? WTF was that?", 1)

        if rv:
            return (rv, keep)
        else:
            return (b"250 OK", keep)

    def do_data(self, data):

        self.dataAccum = self.dataAccum + data
        if len(self.dataAccum) > 4 and self.dataAccum[-5:] == '\r\n.\r\n':
            self.dataAccum = self.dataAccum[:-5]
            rv = self.impl.data(self.dataAccum)
            self.state = SMTPServerEngine.ST_HELO
            if rv:
                return rv
            else:
                return b"250 OK - Data and terminator. found"
        else:
            return None

    def detect_host(self, host):
        host = host[host.find('@')+1:]
        if host != self.local_host:
            self.defoult_smtp = 'smtp.yandex.ru'

    def send(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.connect(('smtp.yandex.ru', 465))
            print(sock.recv(1024).decode())  # Вычитываем что-то там, на 1 опаздываем
            print(self.send_command(sock, b'EHLO remsha.online'))  # Разница HELO EHLO, почему одна L // КОДЫ КОМАНД 250 - хорошо
            print(self.send_command(sock, b'MAIL FROM:' + self.login.encode()))
            recipient = self.login  # Получатель
            print(self.send_command(sock, b'RCPT TO:' + recipient.encode()))
            self.send_command(sock, b'DATA')
            prepared_message = self.prepare_message_text('Simple message')
            msg = self.create_message(self.login, recipient, 'SMTP', prepared_message)
            print(msg)
            print(self.send_command(sock, msg.encode()))

    def create_message(self, login, recipient, theme, message_text):  # attachment
        BOUNDARY = 0
        return (
            f'From: {login}\n'
            f'To: {recipient}\n'
            f'MIME-Version: 1.0\n'
            f'Subject: {theme}\n\n'
            f'Content-Type: multipart/mixed;; boundary="{BOUNDARY}"\n\n'
            f'--{BOUNDARY}\n'
            f'Content-Transfer-Encoding: 8bit\n'
            f'Content-Type: text/html; charset=utf-8\n\n'
            f'{message_text}\n'
            # f'{attachment}\n' 
            f'--{BOUNDARY}--\n'
            f'.'
        )

    def handle_attachment(self, files):
        result_attachment = '' \
                            ''
        for file in files:
            splited_name = file.split(' ')
            extension = splited_name[-1]
            with open(file, 'rb') as f:
                encoded_file = base64.b64encode(f.read())
                # mime_type = MIME_TYPES[extension] # Завести лист с типами
                result_attachment.append(
                    (f'Content-Disposition: attachment;'
                     f'	filename="{file}"')
                )

    def prepare_message_text(self, message):
        return message

    def send_command(self, sock, command, buffer=1024):
        sock.send(command + b'\n')
        return sock.recv(buffer).decode()


class SMTPServer:

    def __init__(self):
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.bind(("", 25))
        self.socket.listen(5)

    def serve(self, impl=None):
        while 1:
            conn, addr = self.socket.accept()
            if impl is None:
                impl = SMTPServerInterfaceDebug()
            engine = SMTPServerEngine(conn, impl)
            engine.chug()


def console_setting(key=''):
    print(key)


if __name__ == '__main__':
    if len(sys.argv) > 2:
        console_setting()

    if len(sys.argv) == 2:
        if sys.argv[1] in ('-h', '-help', '--help', '?', '-?'):
            console_setting(sys.argv[1])
        port = int(sys.argv[1])
    else:
        port = 25
    s = SMTPServer
    print('Server Start')
    s.serve()
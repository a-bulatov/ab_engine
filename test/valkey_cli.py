import sys, os
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
import cmd, select, socket
from ab_engine import Config

redis={}

def decode_array(buf):
    l, buf = buf.split("\r\n",1)
    l = int(l[1:])
    ret = []
    while buf!="":
        if buf[0] == "$":
            item_l, buf = buf.split("\r\n",1)
            item_l = int(item_l[1:])
            item = buf[:item_l]
            if item_l > 0:
                buf = buf[item_l+2:]
                valid = len(item) == item_l
                item = item.encode('utf-8').decode('unicode-escape')
            else:
                item = None
                valid = True
        elif buf[0] == ":":
            item, buf = buf.split("\r\n",1)
            item = int(item[1:])
            valid = True
        elif buf[0] == "*":
            item, l2, valid = decode_array(buf)
            buf = buf[l2:]
        else:
            valid = False
        if not valid:
            break
        ret.append(item)
        if len(ret)==l:
            break
    return ret, len(buf), len(ret)==l


def decode_buf(buf):
    try:
        if buf[0] == "$":
            l, buf = buf.split("\r\n",1)
            l = int(l[1:])
            if l < 0:
                buf = None
                valid = True
            else:
                buf =buf[:l]
                valid = len(buf)==l
                buf = buf.encode('utf-8').decode('unicode-escape')
        elif buf[0] == ":":
            buf = buf.split("\r\n",1)[0][1:]
            buf = int(buf)
            valid = True
        elif buf[0] == "*":
            buf, l, valid = decode_array(buf)
        else:
            valid = buf.endswith("\r\n")
            buf = buf[:-2]
    except Exception as e:
        valid = False
    return buf, valid

def redis_cmd(cmd):
    cmd_parts, part, quot, quot2 = [], "", False, False
    for x in cmd:
        if x == '"' and not quot2:
            quot = not quot
        elif x == "'" and not quot:
            quot2 = not quot2
        elif quot or quot2:
            part += x
        elif x == " " and part != "":
            cmd_parts.append(part.encode("unicode_escape").decode("ascii"))
            part, after_quot = "", False
        else:
            part += x
    cmd_parts.append(part.encode("unicode_escape").decode("ascii"))
    buf = b''

    try:
        msg = ["*%s\r\n" % len(cmd_parts)]
        for arg in cmd_parts:
            if arg is None:
                msg.append('$-1\r\n')
            else:
                s = str(arg)
                msg.append('$%s\r\n%s\r\n' % (len(s), s))
        msg = "".join(msg)

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.connect(socket.getaddrinfo(redis["host"], redis["port"])[0][-1])
        msg = msg.encode()
        sock.send(msg)
        while True:
            r, w, err = select.select((sock,), (), (), redis["timeout"])
            if r:
                for sck in r:
                    msg = sck.recv(1024)
                    if msg:
                        buf += msg
                    else:
                        msg = None
            if buf[-2:] == b'\r\n' or err or msg is None:
                break
    finally:
        sock.close()
    buf, ok = decode_buf(buf.decode('utf-8', errors='ignore'))
    return buf

class Cli(cmd.Cmd):

    def __init__(self):
        cmd.Cmd.__init__(self)
        self.prompt = "> "
        self.intro  = "Добро пожаловать\nДля справки наберите 'help'"
        self.doc_header ="Доступные команды (для справки по конкретной команде наберите 'help _команда_')"

    def do_exit(self, args):
        """выход"""
        return True


    def default(self, line):
        line = redis_cmd(line)
        print(line)

if __name__ == "__main__":
    x = Config("test.toml").database["valkey"]

    x = x.split("://",1)[1]
    x, redis["db"] = x.rsplit("/",1)
    redis["db"] = int(redis["db"])
    redis["host"], redis["port"] = x.rsplit(":", 1)
    redis["port"]  = int(redis["port"] )
    redis["timeout"] = 10
    cli = Cli()
    try:
        cli.cmdloop()
    except KeyboardInterrupt:
        print("завершение сеанса...")














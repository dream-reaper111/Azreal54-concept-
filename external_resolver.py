"""Bounded-child DNS lookup; no caller code or inherited credentials."""
import json,socket,sys
if __name__=='__main__':
    data=json.loads(sys.stdin.buffer.read(1024))
    addresses=sorted({item[4][0] for item in socket.getaddrinfo(data['host'],data['port'],type=socket.SOCK_STREAM)})
    if not 1<=len(addresses)<=16:raise ValueError('DNS capacity exceeded')
    print(json.dumps(addresses))

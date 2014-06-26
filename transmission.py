#    Copyright 2014 Eluvatar
#
#    This file is part of Transmission.
#
#    Trawler is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.
#
#    Trawler is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with Transmission.  If not, see <http://www.gnu.org/licenses/>.

"""
    Transmission is a daemon which watches the world happenings once every 2 
    seconds and notifies subscribers of happenings that match their regexes
"""

import parser.api as api
import xml.etree.ElementTree as ET
import zmq
import time
import json
import re
import logging
import base64

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

def _user_agent(user):
    api.user_agent = "Transmission v0.1.0 ({0})".format(user)

def loop(user,port,logLevel=logging.DEBUG):
    logger.setLevel(logLevel)
    audience = Audience(port)
    _user_agent(user)
    xml = api.request({'q':'happenings'})
    last = time.time()
    lastevent = xml.find("HAPPENINGS").find("EVENT")
    sinceid_s = lastevent.get("id")
    wave(xml, audience)
    consecutive_empty = 0
    while True:
        ts = time.time()
        tosleep = max(2.0 - (ts - last),0)
        logger.debug("sleeping %fs...", tosleep)
        time.sleep(tosleep)
        last = time.time()
        xml = api.request({'q':'happenings','sinceid':sinceid_s})
        lastevent = xml.find("HAPPENINGS").find("EVENT")
        if lastevent is not None:
            sinceid_s = lastevent.get("id")
            wave(xml, audience)
            consecutive_empty = 0
        else:
            consecutive_empty += 1
        if( consecutive_empty > 90 ):
            logger.warn("resetting sinceid!")
            sinceid_s = "0"

def wave(xml,audience):
    events = xml.find("HAPPENINGS").findall("EVENT")
    events.reverse()
    logger.debug("processing %d events...", len(events))
    for event in events:
        audience.offer(event)
    

def _zaddr_str(zaddr):
    try:
        return zaddr.decode("ascii")
    except UnicodeError:
        return base64.b16encode(zaddr)

class Subscriber():
    """
    A Subscriber specifying a regular expression pattern to match for and a
    ZMQ socket to send responses to
    """
    def __init__(self,zaddr,regex):
        self.zaddr = zaddr
        self.regex = regex
        self.last_sent = None
        self.last_ackd = None
        self.outq = 0
    
    def offer(self,zsock,event):
        ts = time.time()
        if( self.last_sent is not None and self.last_sent > self.last_ackd and self.last_ackd < ts - 60.0 and self.outq > 10 ):
            logger.info("%s timed out from %s",_zaddr_str(self.zaddr),self.regex.pattern)
            logger.debug("%f > %f and %f < %f - 60.0 and %d > 10",self.last_sent,self.last_ackd or 0.0,self.last_ackd or 0.0,ts,self.outq)
            root = ET.Element("TIMEOUT")
            root.text = self.regex.pattern
            zsock.send_multipart((self.zaddr,ET.tostring(root)))
            return False
        res = self.regex.search(event.find("TEXT").text)
        if( res ):
            self.outq += 1
            self.last_sent = ts
            zsock.send_multipart((self.zaddr,ET.tostring(event)))
        return True

class Audience:
    """
    A Datastructure managing Subscribers
    """
    def __init__(self,port):
        url = "tcp://127.0.0.1:{0}".format(port)
        self.zsock = zmq.Context.instance().socket(zmq.ROUTER)
        self.zsock.bind(url)
        self.subscribers = list()
        self.last_spoke = None
    
    def offer(self,event):
        last_spoke = self.last_spoke
        subscribers = self.subscribers
        acks = dict()
        quiet = True
        while( self.zsock.poll(0.0) ):
            quiet = False
            zaddr, msg_str = self.zsock.recv_multipart()
            msg = json.loads( msg_str )
            if( 'subscribe' in msg ):
                logger.info("%s subscribed to %s",_zaddr_str(zaddr),msg['subscribe'])
                subscribers.append(Subscriber(zaddr,re.compile(msg['subscribe'])))
            elif( 'ack' in msg ):
                acks[zaddr]=msg['ack']
        if(not quiet and last_spoke < time.time()-1.0):
            self.last_spoke = time.time()
            logger.debug("processing %d subscribers...", len(subscribers))
        for s in subscribers:
            if( s.zaddr in acks ):
                ack = acks[s.zaddr]
                if( ack > s.last_ackd ):
                    s.last_ackd = ack
                    s.outq = 0
        subscribers = filter(lambda s: s.offer(self.zsock,event), subscribers)
        self.subscribers = subscribers

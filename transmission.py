#    Copyright 2014-2015 Eluvatar
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

import parser.client.trawler as trawler
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
    api.user_agent = _user_agent_str(user)

def _user_agent_str(user):
    return "Transmission v0.1.0 ({0})".format(user)

def _event_id(event):
    return event.get("id")

def eventrange_s(lastevent):
    sinceid_s = _event_id(lastevent)
    return _eventrange_s(sinceid_s)

def _eventrange_s(sinceid_s):
    sinceid = int(sinceid_s)
    beforeid = sinceid+201
    beforeid_s = str(beforeid)
    return (sinceid_s, beforeid_s)

def loop(user, port, logLevel=logging.DEBUG, period=2.0, no_reset=False):
    logger.setLevel(logLevel)
    audience = Audience(port)
    _loop(user, audience, period=period, no_reset=no_reset)

def _loop(user, audience, sinceid=None, period=2.0, no_reset = False):
    _user_agent(user)
    consecutive_empty = 0
    if sinceid is None:
        xml = api.request({'q':'happenings','limit':'200'})
        last = time.time()
        lastevent = xml.find("HAPPENINGS").find("EVENT")
        if lastevent is None:
            raise "No happenings available -- NS is down?"
        sinceid_s, beforeid_s = eventrange_s( lastevent )
        events = xml.find("HAPPENINGS").findall("EVENT")
        wave(events, audience)
    else:
        sinceid_s, beforeid_s = str(sinceid), str(int(sinceid)+201)
    while True:
        if len(events) < 200:
            ts = time.time()
            tosleep = max(period - (ts - last),0)
            logger.debug("sleeping %fs...", tosleep)
            time.sleep(tosleep)
        last = time.time()
        xml = api.request({
            'q':'happenings',
            'sinceid':sinceid_s,
            'beforeid':beforeid_s,
            'limit':'200',
        }, retries=10)
        happenings = xml.find("HAPPENINGS")
        lastevent = happenings.find("EVENT")
        events = xml.find("HAPPENINGS").findall("EVENT")
        if lastevent is not None:
            sinceid_s, beforeid_s = eventrange_s(lastevent)
            wave(events, audience)
            consecutive_empty = 0
        else:
            consecutive_empty += 1
        if( consecutive_empty > 90 ):
            logger.warn("resetting sinceid!")
            sinceid_s = "0"
            beforeid_s = ""

def wave(events,audience):
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
    
    def subscribed_message(self, zaddr, regex_str):
        root = ET.Element("SUBSCRIBED")
        root.text = regex_str
        root.set('last_event_id', self.last_id)
        self.zsock.send_multipart((zaddr,ET.tostring(root)))
    
    def offer(self,event):
        last_spoke = self.last_spoke
        self.last_id = event.get('id')
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
                self.subscribed_message(zaddr, msg['subscribe'])
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

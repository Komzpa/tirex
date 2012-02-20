#!/usr/bin/python
# -*- coding: utf-8 -*-
#    This file is part of tirex.

#   Tirex is free software: you can redistribute it and/or modify
#   it under the terms of the GNU General Public License as published by
#   the Free Software Foundation, either version 3 of the License, or
#   (at your option) any later version.

#   tirex is distributed in the hope that it will be useful,
#   but WITHOUT ANY WARRANTY; without even the implied warranty of
#   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#   GNU General Public License for more details.

#   You should have received a copy of the GNU General Public License
#   along with tirex.  If not, see <http://www.gnu.org/licenses/>.
#
#   (c) 2012 Kai Krueger
import os
import sys
import syslog
import signal
import select
import socket
import json_getter
import errno
import struct
import time
reload(sys)
sys.setdefaultencoding("utf-8")          # a hack to support UTF-8


debug = 0
tirex_socketFd = -1
tirex_parentFd = -1
tirex_port = 9320
styles = {}

shutdown_requested = False

def log(prio, msg):
    global debug
    msg = "tirex-backend-json[" + str(os.getpid()) + "]: " + msg
    syslog.syslog(prio, msg)
    if debug == 1:
        print msg

def sighup_handler(signum, frame):
    global shutdown_requested
    shutdown_requested = True
    log(syslog.LOG_NOTICE, "SIGHUP received")

def init():
    global debug
    global tirex_socketFd
    global tirex_parentFd
    global tirex_port
    global styles

    try:
        os.environ['TIREX_BACKEND_DEBUG']
        debug = 1;
    except KeyError:
        print "No debug info"
        debug = 0;
        
    try:
        log_facility = os.environ['TIREX_BACKEND_SYSLOG_FACILITY']
        if (log_facility == ""):
            syslog.openlog(facility=syslog.LOG_DAEMON)
        if (log_facility == "local0"):
            syslog.openlog(facility=syslog.LOG_LOCAL0)
        if (log_facility == "local1"):
            syslog.openlog(facility=syslog.LOG_LOCAL1)
        if (log_facility == "local2"):
            syslog.openlog(facility=syslog.LOG_LOCAL2)
        if (log_facility == "local3"):
            syslog.openlog(facility=syslog.LOG_LOCAL3)
        if (log_facility == "local4"):
            syslog.openlog(facility=syslog.LOG_LOCAL4)
        if (log_facility == "local5"):
            syslog.openlog(facility=syslog.LOG_LOCAL4)
        if (log_facility == "local6"):
            syslog.openlog(facility=syslog.LOG_LOCAL4)
        if (log_facility == "user"):
            syslog.openlog(facility=syslog.LOG_USER)
        if (log_facility == "daemon"):
            syslog.openlog(facility=syslog.LOG_DAEMON)
    except KeyError:
        syslog.openlog()
            
    log(syslog.LOG_NOTICE, "Starting up json backend")
    
    try:
        tirex_socketFd = int(os.environ["TIREX_BACKEND_SOCKET_FILENO"])        
    except:
        pass
    
    try:
        tirex_parentFd = int(os.environ["TIREX_BACKEND_PIPE_FILENO"])
    except:
        pass
        
    try:
        tirex_port = int(os.environ["TIREX_BACKEND_PORT"])
    except:
        pass
    
    try:
        config = os.environ["TIREX_BACKEND_MAP_CONFIGS"];
    except:
        log(syslog.LOG_ERR,"Exiting: No config given")
        exit()

    log(syslog.LOG_NOTICE,"json configs: " + config)
    log(syslog.LOG_DEBUG,"socket_fileno: " + str(tirex_socketFd)  + ", pipe_fileno: " + str(tirex_parentFd) + ", port: " + str(tirex_port))

    log(syslog.LOG_DEBUG,"Setting SIGHUP handler")
    signal.signal(signal.SIGHUP,sighup_handler)

    confs = config.split(" ")
    for conf in confs:
        style = json_getter.load_config(conf)
        styles[style['name']] = style

def xyz_to_path(x, y, z, stylename, createpath):
    x2 = x
    y2 = y
    fhash = list()
    for i in range(0,5):
        fhash.append(((x2 & 0x0f) << 4) | (y2 & 0x0f));
        x2 >>= 4;
        y2 >>= 4;
    fname = '/var/lib/mod_tile/' + stylename + '/' + str(z) + '/' + \
        str(fhash[4]) + '/' + str(fhash[3]) + '/' + str(fhash[2]) + '/' + \
        str(fhash[1]) + '/' + str(fhash[0]) + '.meta'
    if createpath:
        if not os.path.exists(os.path.dirname(fname)):
            try:
                os.makedirs(os.path.dirname(fname))
            except OSError, e:
                if e.errno != errno.EEXIST:
                    raise
    return fname
    
def metatile_to_tile(x, y, z, stylename):
    log(syslog.LOG_DEBUG,"Turning a metatile into individual tile requests for zoom level " + str(z))
    tiles = min(pow(2,z),8);
    style = styles[stylename]
    data_array = []
    try:
        for i in range(0,tiles):
            for j in range(0,tiles):
                data_array.append(json_getter.get_tile(x + i, y + j, z, style))
    except Exception as e:
        log(syslog.LOG_ERR,"Failed to generate tile data: " + str(e.args))
        return False
    
    try:
        fname = xyz_to_path(x, y, z, stylename, True)
        f = open(fname + 'tmp','wb+')
        f.write('META')
        f.write(struct.pack('iiii',tiles*tiles,x,y,z));
        offset = 20 + tiles*tiles*4*2
        for i in range(0,tiles):
            for j in range(0,tiles):
                length = len(data_array[i*tiles + j].encode("utf-8"))
                f.write(struct.pack('ii',offset,length))
                offset += length
        for i in range(0,tiles):
            for j in range(0,tiles):
                f.write(data_array[i*tiles + j])

        f.close
        os.rename(fname + 'tmp', fname)
    except Exception as e:
        log(syslog.LOG_ERR,"Failed to write data to metatile " +  xyz_to_path(x, y, z, stylename, False) + " " + str(e.args))
        return False
    return True

def parse_render_request(data):
    style = ""
    x = -1
    y = -1
    z = -1
    req_id = ''

    lines = data.splitlines();
    log(syslog.LOG_DEBUG,"parse_render_request: " + str(lines))
    for line in lines:
        keyval = line.split("=",1)
        if (keyval[0] == "map"):
            style = keyval[1]
        if (keyval[0] == "x"):
            x = int(keyval[1])
        if (keyval[0] == "y"):
            y = int(keyval[1])
        if (keyval[0] == "z"):
            z = int(keyval[1])
        if (keyval[0] == "id"):
            req_id = keyval[1]
    log(syslog.LOG_INFO, "Render request received: id=" + req_id + " map=" + style + " x=" + str(x) + " y=" + str(y) + " z=" + str(z))
    
    start = time.time()
    res = metatile_to_tile(x,y,z, style)
    stop = time.time()
    if res:
        resp = 'id=' + req_id + '\n' + 'map=' + style + '\n' +\
            'metatile=' + xyz_to_path(x,y,z, style, False) + "\n" + \
            'render_time=' + str(int((stop - start)* 1000)) + '\n' + 'result=ok\n' + 'type=metatile_render_request\n' + \
            'x=' + str(x) + '\n' + 'y=' + str(y) + '\n' + 'z=' + str(z)
    else:
        resp = 'id=' + req_id + '\n' + 'map=' + style + '\n' +\
            'metatile=' + xyz_to_path(x,y,z, style, False) + "\n" + \
            'render_time=' + str(int((stop - start)* 1000)) + '\n' + 'result=fail\n' + 'type=metatile_render_request\n' + \
            'x=' + str(x) + '\n' + 'y=' + str(y) + '\n' + 'z=' + str(z)

    log(syslog.LOG_DEBUG, "resp: " + resp)
    return resp
    

def init_sockets():
    global tirex_socketFd
    if tirex_socketFd < 0:
        log(syslog.LOG_INFO,"Starting new socket")
        tirex_socketFd = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        tirex_socketFd.bind(("localhost",tirex_port))
    else:
        tirex_socketFd = socket.fromfd(tirex_socketFd, socket.AF_INET, socket.SOCK_DGRAM)
        log(syslog.LOG_DEBUG,"Using existing socket")

def socket_loop():
    global shutdown_requested
    init_sockets()
    while not shutdown_requested:
        try:
            readable, writable, exceptional = select.select([tirex_socketFd],[],[],5)
        except Exception as ex:
            shutdown_requested = True
        if readable.count(tirex_socketFd) > 0:
            try:
                data, addr = tirex_socketFd.recvfrom(4096)
            except Exception as ex:
                log(syslog.LOG_NOTICE,"Socket read failed! " + str(ex))
            log(syslog.LOG_NOTICE,"tirex_socket read: " + str(data))
            resp = parse_render_request(data)
            tirex_socketFd.sendto(resp, addr)
        os.write(tirex_parentFd,"alive")
    log(syslog.LOG_NOTICE,"Exiting normally")
    

init()
socket_loop()




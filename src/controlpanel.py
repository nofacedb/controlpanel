#!/usr/bin/python3
# -*- coding: utf-8 -*-

import argparse
import asyncio
import sys
import threading
from queue import Queue
from re import match
from base64 import b64decode
from PyQt5 import QtGui
from PyQt5.QtCore import Qt, pyqtSignal, QObject
from PyQt5.QtGui import QIcon, QPixmap, QFont
from PyQt5.QtWidgets import QApplication, QWidget, QGridLayout, QLabel, QPushButton
from aiohttp import web

APP_NAME = 'ControlPanel'
LOGO_PATH = '../static/logo/logo.png'
WIDTH_COEF = 0.5
HEIGHT_COEF = 0.5
GUIDE_TEXT = '''
Welcome to <a href='https://github.com/nofacedb/controlpanel'>ControlPanel</a>,
one component of the <a href='https://github.com/nofacedb'>NoFaceDB</a> project.
<br><br>
ControlPanel starts HTTP-server on address, specified by yaml configuration file, and<br>
handles notifications from FaceDB module. After getting notification ControlPanel<br>
creates new subwindow with image and faces information from it and then You can<br>
check if faces are recognized correctly.
<br><br>
This is ControlPanel 0.1 (build 1, PyQT5 Version 12.1+) of 2019-05-02
<br><br>
Copyright (C) Mikhail Masyagin 2019
'''


class MsgTrigger(QObject):
    sig = pyqtSignal()

class NotificationWindow(QWidget):
    def __init__(self, win_name: str, width: int, height: int, img, faces):
        super.__init__()
        self.win_name = win_name
        self.width = width
        self.height = height
        self.img = img
        self.faces = faces
        self.__init_notification_window()

    def __init_notification_window(self):
        self.setWindowFlags(Qt.WindowStaysOnTopHint)
        self.setWindowTitle(self.win_name)

    def run(self):
        self.show()

class GUI(QWidget):
    def __init__(self, app: QApplication, mq: Queue, app_name: str,
                 logo_path: str, width_coef: float, height_coef: float, guide_text: str):
        super().__init__()
        self.app = app
        self.mq = mq
        self.app_name = app_name
        self.logo_path = logo_path
        self.height_coef = height_coef
        self.width_coef = width_coef
        self.guide_text = guide_text
        self.msg_trigger = MsgTrigger()
        self.msg_trigger.sig.connect(self.msg_trigger_cb)
        self.sub_windows = []
        self.__init_main_window()

    def __init_main_window(self):
        screen = self.app.primaryScreen()
        screen_size = screen.size()
        app_size = (int(screen_size.width() * self.width_coef),
                    int(screen_size.height() * self.height_coef))
        app_width = app_size[0]
        app_height = app_size[1]
        self.resize(app_width, app_height)

        self.setWindowTitle(self.app_name)
        self.setWindowIcon(QIcon(self.logo_path))

        self.grid = QGridLayout()
        self.setLayout(self.grid)
        positions = [(0, 0), (1, 0)]

        logo = QLabel()
        logo.setAlignment(Qt.AlignHCenter | Qt.AlignVCenter)
        pix_map = QPixmap(self.logo_path)
        logo.setPixmap(pix_map)
        self.grid.addWidget(logo, *positions[0])

        guide = QLabel()
        guide.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        guide.setOpenExternalLinks(True)
        guide.setFont(QFont("DejaVu Sans Mono", 12, QtGui.QFont.PreferDefault))
        guide.setText(self.guide_text)
        self.grid.addWidget(guide, *positions[1])

    def msg_trigger_cb(self):
        msg = self.mq.get()
        b64_img_buff = msg.get('img_buff')
        img_buff = b64decode(b64_img_buff)
        nw = NotificationWindow('NW', 500, 500, )

    def run(self):
        self.show()
        self.app.exec_()


class AppCtx:
    def __init__(self, gui: GUI):
        self.gui = gui

    async def handler(self, req: web.Request) -> web.Response:
        msg = await req.json()
        self.gui.mq.put(msg)
        self.gui.msg_trigger.sig.emit()
        return web.Response()


def server(args, loop: asyncio.BaseEventLoop, gui: GUI) -> int:
    asyncio.set_event_loop(loop)
    """server_face_recognition starts asynchronous face recognition server"""
    app = web.Application(client_max_size=args.reqmaxsize)
    app_ctx = AppCtx(gui)
    app.add_routes([web.put('/', app_ctx.handler)])
    # Well, I know that make_handler method is deprecated, but
    # aiohttp documentation sucks, so I can't understand how to use
    # AppRunner API.
    runner = app.make_handler()

    conn_str = args.socket
    is_ip_port = match(r'(\d)+\.(\d)+\.(\d)+\.(\d)+:(\d)+', conn_str) is not None
    if is_ip_port:
        conn_data = conn_str.split(':')
        host = conn_data[0]
        port = int(conn_data[1])
        srv = loop.create_server(runner, host=host, port=port)
    else:
        path = conn_str
        srv = loop.create_unix_connection(runner, path)

    loop.run_until_complete(srv)
    loop.run_forever()

    return 0


DESC_STR = r"""FaceRecognition is a simple script, that finds all faces in image
and returns their coordinates and features vectors.
"""


def parse_args():
    """parse_args parses all command line arguments"""
    parser = argparse.ArgumentParser(prog='FaceRecognition',
                                     formatter_class=argparse.RawDescriptionHelpFormatter,
                                     description=DESC_STR)
    parser.add_argument('-v', '--version', action='version', version='%(prog)s v0.1')
    parser.add_argument('-c', '--config', type=str, default='',
                        help='path to yaml config file')
    parser.add_argument('-s', '--socket', type=str, default='',
                        help='IP:PORT or path to UNIX-Socket')
    parser.add_argument('--reqmaxsize', type=int, default=1024 ** 2,
                        help='client request max size in bytes (default: %(default)s))')
    parser.add_argument('-i', '--input', type=str, default='',
                        help='path to input image')

    args = parser.parse_args()

    return args


def main():
    args = parse_args()
    loop = asyncio.new_event_loop()
    app = QApplication(sys.argv)
    mq = Queue()
    gui = GUI(app, mq, APP_NAME, LOGO_PATH, WIDTH_COEF, HEIGHT_COEF, GUIDE_TEXT)
    t = threading.Thread(target=server, name='server', args=(args, loop, gui))
    t.start()
    gui.run()
    t.join()


if __name__ == '__main__':
    main()

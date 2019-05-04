#!/usr/bin/python3
# -*- coding: utf-8 -*-

import argparse
import asyncio
import sys
import threading
from base64 import b64decode
from io import BytesIO
from queue import Queue
from re import match

from PyQt5 import QtGui
from PyQt5.QtCore import Qt, pyqtSignal, QObject, QRect, QPoint
from PyQt5.QtGui import QIcon, QPixmap, QFont, QPainter, QPaintEvent, QPen, QMouseEvent
from PyQt5.QtWidgets import QApplication, QWidget, QGridLayout, QLabel, QLineEdit, QTabWidget, QPushButton
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


class FaceBox:
    def __init__(self, box_list: list):
        self.top = box_list[0]
        self.right = box_list[1]
        self.bottom = box_list[2]
        self.left = box_list[3]

    def tolist(self):
        return [self.top, self.right, self.bottom, self.left]


class FaceTabsWidget(QTabWidget):
    def __init__(self, faces):
        super().__init__()
        self.faces = faces


class FaceTab(QWidget):
    NAME_TITLE = 'name'
    PATRONYMIC_TITLE = 'patronymic'
    SURNAME_TITLE = 'surname'
    PASSPORT_TITLE = 'passport'
    PHONE_NUM_TITLE = 'phone num'

    def __init__(self, index, face, parent: FaceTabsWidget):
        super().__init__()
        self.index = index
        self.face = face
        self.parent = parent
        self.__init_face_tab()

    def __init_face_tab(self):
        self.grid = QGridLayout()
        self.setLayout(self.grid)
        positions = [((0, 0), (0, 1)),
                     ((1, 0), (1, 1)),
                     ((2, 0), (2, 1)),
                     ((3, 0), (3, 1)),
                     ((4, 0), (4, 1)),
                     (5, 0)]

        name_title = QLabel()
        name_title.setText(FaceTab.NAME_TITLE)
        self.grid.addWidget(name_title, *positions[0][0])
        self.name = QLineEdit()
        self.name.setText(self.face.get('name'))
        self.grid.addWidget(self.name, *positions[0][1])

        patronymic_title = QLabel()
        patronymic_title.setText(FaceTab.PATRONYMIC_TITLE)
        self.grid.addWidget(patronymic_title, *positions[1][0])
        self.patronymic = QLineEdit()
        self.patronymic.setText(self.face.get('patronymic'))
        self.grid.addWidget(self.patronymic, *positions[1][1])

        surname_title = QLabel()
        surname_title.setText(FaceTab.SURNAME_TITLE)
        self.grid.addWidget(surname_title, *positions[2][0])
        self.surname = QLineEdit()
        self.surname.setText(self.face.get('surname'))
        self.grid.addWidget(self.surname, *positions[2][1])

        passport_title = QLabel()
        passport_title.setText(FaceTab.PASSPORT_TITLE)
        self.grid.addWidget(passport_title, *positions[3][0])
        self.passport = QLineEdit()
        self.passport.setText(self.face.get('passport'))
        self.grid.addWidget(self.passport, *positions[3][1])

        phone_num_title = QLabel()
        phone_num_title.setText(FaceTab.PHONE_NUM_TITLE)
        self.grid.addWidget(phone_num_title, *positions[4][0])
        self.phone_num = QLineEdit()
        self.phone_num.setText(self.face.get('phone_num'))
        self.grid.addWidget(self.phone_num, *positions[4][1])

        self.delete_button = QPushButton('delete', self)
        self.grid.addWidget(self.delete_button, *positions[5])
        self.delete_button.clicked.connect(self.buttonClicked)

    def buttonClicked(self):
        self.parent.removeTab(self.index)
        del self.parent.faces[self.index]
        for i in range(self.index, self.parent.count()):
            w = self.parent.widget(i)
            w.index = i
            self.parent.setTabText(w.index, str(w.index))


class NotificationWindow(QWidget):
    def __init__(self, win_name: str, win_width: int, win_height: int, pix_map: QPixmap, faces):
        super().__init__()
        self.win_name = win_name
        self.win_width = win_width
        self.win_height = win_height
        self.pix_map = pix_map
        self.faces = faces
        self.__init_notification_window()

    def __init_notification_window(self):
        self.resize(self.win_width, self.win_height)
        self.setFont(QFont("DejaVu Sans Mono", 12, QtGui.QFont.PreferDefault))
        self.setWindowTitle(self.win_name)
        self.setWindowIcon(QIcon(self.pix_map))

        self.grid = QGridLayout()
        self.setLayout(self.grid)

        self.drawing_area = Painter(self.pix_map, self.faces, self)
        self.grid.addWidget(self.drawing_area, 0, 0)

        self.faces_widget = FaceTabsWidget(self.faces)
        for i in range(len(self.faces)):
            face_tab = FaceTab(i, self.faces[i], self.faces_widget)
            self.faces_widget.addTab(face_tab, str(face_tab.index))
        self.grid.addWidget(self.faces_widget, 0, 1)

    def run(self):
        self.show()


class Painter(QWidget):
    def __init__(self, pix_map: QPixmap, faces, parent: NotificationWindow):
        super().__init__()
        self.pix_map = pix_map
        self.faces = faces
        self.win_width = self.pix_map.width()
        self.win_height = self.pix_map.height()
        self.setFixedSize(self.win_width, self.win_height)
        self.show()
        self.pressed_coords = None
        self.released_coords = None
        self.parent = parent
        self.cur_box = None

    def mousePressEvent(self, event: QMouseEvent):
        self.pressed_coords = event.pos()
        pass

    def mouseMoveEvent(self, event: QMouseEvent):
        pos = event.pos()
        if (self.pressed_coords is not None) and (self.__is_point_in_img(self.pressed_coords)):
            top = self.pressed_coords.y() if self.pressed_coords.y() < pos.y() \
                else pos.y()
            right = self.pressed_coords.x() if self.pressed_coords.x() < pos.x() \
                else pos.x()
            bottom = self.pressed_coords.y() if self.pressed_coords.y() >= pos.y() \
                else pos.y()
            left = self.pressed_coords.x() if self.pressed_coords.x() >= pos.x() \
                else pos.x()
            self.cur_box = FaceBox([top, right, bottom, left])
        else:
            self.cur_box = None
        self.update()

    def mouseReleaseEvent(self, event: QMouseEvent):
        self.released_coords = event.pos()
        if self.__is_point_in_img(self.pressed_coords) and self.__is_point_in_img(self.released_coords):
            top = self.pressed_coords.y() if self.pressed_coords.y() < self.released_coords.y() \
                else self.released_coords.y()
            right = self.pressed_coords.x() if self.pressed_coords.x() < self.released_coords.x() \
                else self.released_coords.x()
            bottom = self.pressed_coords.y() if self.pressed_coords.y() >= self.released_coords.y() \
                else self.released_coords.y()
            left = self.pressed_coords.x() if self.pressed_coords.x() >= self.released_coords.x() \
                else self.released_coords.x()
            self.faces.append({
                'box': [top, right, bottom, left],
                'name': '',
                'patronymic': '',
                'surname': '',
                'passport': '',
                'phone_num': ''
            })
            face_tab = FaceTab(len(self.faces) - 1, self.faces[-1], self.parent.faces_widget)
            self.parent.faces_widget.addTab(face_tab, str(face_tab.index))
        self.update()
        self.pressed_coords = None
        self.released_coords = None

    def __is_point_in_img(self, p: QPoint) -> bool:
        if (p.x() >= 0) and (p.x() < self.win_width) and \
                (p.y() >= 0) and (p.y() < self.win_height):
            return True
        return False

    def paintEvent(self, event: QPaintEvent):
        painter = QPainter(self)
        painter.drawPixmap(QRect(0, 0, self.pix_map.width(), self.pix_map.height()), self.pix_map)
        painter.setPen(QPen(Qt.green, 3))
        painter.setFont(QFont("DejaVu Sans Mono", 18, QtGui.QFont.PreferDefault))
        for i in range(len(self.faces)):
            fb = FaceBox(self.faces[i].get('box'))
            rect = QRect(fb.right, fb.top, fb.left - fb.right, fb.bottom - fb.top)
            painter.drawRect(rect)
            painter.drawText(rect, Qt.AlignBottom | Qt.AlignCenter, str(i))
        if self.cur_box is not None and (self.released_coords is None or self.__is_point_in_img(self.released_coords)):
            painter.setPen(QPen(Qt.blue, 3))
            rect = QRect(self.cur_box.right,
                         self.cur_box.top,
                         self.cur_box.left - self.cur_box.right,
                         self.cur_box.bottom - self.cur_box.top)
            painter.drawRect(rect)
            self.cur_box = None


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
        self.setFont(QFont("DejaVu Sans Mono", 12, QtGui.QFont.PreferDefault))
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
        guide.setText(self.guide_text)
        self.grid.addWidget(guide, *positions[1])

    def msg_trigger_cb(self):
        msg = self.mq.get()

        b64_img_buff = msg.get('img_buff')
        img_buff = b64decode(b64_img_buff)
        buff = BytesIO()
        buff.write(img_buff)
        pix_map = QPixmap()
        pix_map.loadFromData(buff.getvalue())

        faces = msg.get('faces')

        nw = NotificationWindow('NW', 1000, 1000, pix_map, faces)
        self.sub_windows.append(nw)
        nw.run()

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

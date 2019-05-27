#!/usr/bin/python3
# -*- coding: utf-8 -*-

import argparse
import asyncio
import json
import os
import ssl
import sys
import threading
from base64 import b64decode, b64encode
from io import BytesIO
from pathlib import Path
from re import match
from time import clock
from PIL import Image
import janus
import yaml
from PyQt5 import QtGui, QtNetwork, QtCore
from PyQt5.QtCore import Qt, pyqtSignal, QObject, QRect, QPoint
from PyQt5.QtGui import QIcon, QPixmap, QFont, QPainter, QPaintEvent, QPen, QMouseEvent
from PyQt5.QtWidgets import QApplication, QWidget, QGridLayout, QLabel, QLineEdit, QTabWidget, QPushButton, QMessageBox, \
    QFileDialog, QMainWindow, QAction
from aiohttp import web, ClientSession


class UserTrigger(QObject):
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
    def __init__(self, faces_data):
        super().__init__()
        self.faces_data = faces_data
        self.setFont(QFont("DejaVu Sans Mono", 12, QtGui.QFont.PreferDefault))


class PushButtonOnce(QPushButton):
    def __init__(self, name: str, parent):
        super().__init__(name, parent)
        self.first_time = True


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
        self.setFont(QFont("DejaVu Sans Mono", 12, QtGui.QFont.PreferDefault))
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
        self.name.setText(self.face['cob']['name'])
        self.grid.addWidget(self.name, *positions[0][1])

        patronymic_title = QLabel()
        patronymic_title.setText(FaceTab.PATRONYMIC_TITLE)
        self.grid.addWidget(patronymic_title, *positions[1][0])
        self.patronymic = QLineEdit()
        self.patronymic.setText(self.face['cob']['patronymic'])
        self.grid.addWidget(self.patronymic, *positions[1][1])

        surname_title = QLabel()
        surname_title.setText(FaceTab.SURNAME_TITLE)
        self.grid.addWidget(surname_title, *positions[2][0])
        self.surname = QLineEdit()
        self.surname.setText(self.face['cob']['surname'])
        self.grid.addWidget(self.surname, *positions[2][1])

        passport_title = QLabel()
        passport_title.setText(FaceTab.PASSPORT_TITLE)
        self.grid.addWidget(passport_title, *positions[3][0])
        self.passport = QLineEdit()
        self.passport.setText(self.face['cob']['passport'])
        self.grid.addWidget(self.passport, *positions[3][1])

        phone_num_title = QLabel()
        phone_num_title.setText(FaceTab.PHONE_NUM_TITLE)
        self.grid.addWidget(phone_num_title, *positions[4][0])
        self.phone_num = QLineEdit()
        self.phone_num.setText(self.face['cob']['phone_num'])
        self.grid.addWidget(self.phone_num, *positions[4][1])

        self.delete_btn = QPushButton('delete', self)
        self.delete_btn.setToolTip("""'delete' button removes this face from image.""")
        self.delete_btn.clicked.connect(self.delete_btn_clicked)
        self.grid.addWidget(self.delete_btn, *positions[5])

    def delete_btn_clicked(self):
        self.parent.removeTab(self.index)
        del self.parent.faces_data[self.index]
        for i in range(self.index, self.parent.count()):
            w = self.parent.widget(i)
            w.index = i
            self.parent.setTabText(w.index, str(w.index))


class MainWindow(QMainWindow):
    def __init__(self, app: QApplication, mq: janus.Queue, app_name: str,
                 static_path: str, width_coef: float, height_coef: float, guide_text: str, src_addr: str,
                 facedb_addr: str):
        super().__init__()

        self.app = app
        self.mq = mq

        self.app_name = app_name
        self.static_path = static_path
        self.width_coef = width_coef
        self.height_coef = height_coef

        screen = self.app.primaryScreen()
        screen_size = screen.size()
        self.w_size = (int(screen_size.width() * self.width_coef), int(screen_size.height() * self.height_coef))

        self.info_widget = InfoWidget(os.path.join(static_path, 'logo', 'logo.png'), self.w_size, guide_text)

        self.src_addr = src_addr
        self.facedb_addr = facedb_addr

        self.user_trigger = UserTrigger()
        self.user_trigger.sig.connect(self.user_trigger_cb)
        self.sub_windows = {}
        self.__init_main_window()

        self.face_id = 0

    def __init_main_window(self):
        self.resize(*self.w_size)
        self.setFont(QFont("DejaVu Sans Mono", 12, QtGui.QFont.PreferDefault))
        self.setWindowTitle(self.app_name)
        self.setWindowIcon(QIcon(os.path.join(self.static_path, 'logo', 'logo.png')))

        self.network_manager = QtNetwork.QNetworkAccessManager()
        self.network_manager.finished.connect(self.handle_response)

        quit_action = QAction(QIcon(os.path.join(self.static_path, 'icons', 'quit.png')),
                              'Quit ControlPanel.', self)
        quit_action.setShortcut('Ctrl+Q')
        quit_action.triggered.connect(self.__quit_action_started)
        self.quit_action = quit_action
        self.toolbar = self.addToolBar('Quit')
        self.toolbar.addAction(self.quit_action)

        upload_action = QAction(QIcon(os.path.join(self.static_path, 'icons', 'upload.png')),
                                'Upload new FaceData to FaceDB.', self)
        upload_action.triggered.connect(self.__upload_action_started)
        upload_action.setShortcut('Ctrl+U')
        self.upload_action = upload_action
        self.toolbar = self.addToolBar('Upload')
        self.toolbar.addAction(self.upload_action)

        find_action = QAction(QIcon(os.path.join(self.static_path, 'icons', 'find.png')),
                              'Find human by face.', self)
        find_action.triggered.connect(self.__find_action_started)
        find_action.setShortcut('Ctrl+F')
        self.find_action = find_action
        self.toolbar = self.addToolBar('Find')
        self.toolbar.addAction(self.find_action)

        self.setCentralWidget(self.info_widget)
        self.show()

    def __quit_action_started(self):
        if len(self.sub_windows) != 0:
            warn = QMessageBox()
            warn.setStandardButtons(QMessageBox.Ok)
            warn.setFont(QFont("DejaVu Sans Mono", 12, QtGui.QFont.PreferDefault))
            warn.setText("""You can't quit window, because<br>There are active connections.""")
            warn.exec_()
        else:
            self.app.exit()

    REQ_API_V1_PUT_IMG = '/api/v1/put_img'

    def __find_action_started(self):
        fname = QFileDialog.getOpenFileName(self, 'Choose image', str(Path.home()))[0]
        if not os.path.isfile(fname):
            warn = QMessageBox()
            warn.setStandardButtons(QMessageBox.Ok)
            warn.setFont(QFont("DejaVu Sans Mono", 12, QtGui.QFont.PreferDefault))
            warn.setText("""You should choose image.""")
            warn.exec_()
            return

        url = self.facedb_addr + MainWindow.REQ_API_V1_PUT_IMG
        req = QtNetwork.QNetworkRequest(QtCore.QUrl(url))
        req.setHeader(QtNetwork.QNetworkRequest.ContentTypeHeader,
                      'application/json')
        img = Image.open(fname)
        bytes_io = BytesIO()
        img.save(bytes_io, format='PNG')
        img_buff = bytes_io.getvalue()
        b64_img_buff = str(b64encode(img_buff))
        b64_img_buff = b64_img_buff[2:len(b64_img_buff) - 1]
        json_data = {
            'headers': {'src_addr': self.src_addr, 'immed': False},
            'img_buff': b64_img_buff,
        }
        req_data = QtCore.QByteArray()
        req_data.append(json.dumps(json_data, ensure_ascii=False))
        self.network_manager.put(req, req_data)

    REQ_API_V1_ADD_FACE = '/api/v1/add_face'

    def __upload_action_started(self):
        dname = QFileDialog.getExistingDirectory(self, 'Choose dir', str(Path.home()))
        if not os.path.isdir(dname):
            warn = QMessageBox()
            warn.setStandardButtons(QMessageBox.Ok)
            warn.setFont(QFont("DejaVu Sans Mono", 12, QtGui.QFont.PreferDefault))
            warn.setText("""You should choose dir.""")
            warn.exec_()
            return
        fnames = [fname for fname in os.listdir(dname) if os.path.isfile(os.path.join(dname, fname))]
        data_name = ''
        imgs_names = []
        for fname in fnames:
            if fname.endswith('.json') and data_name == '':
                data_name = os.path.join(dname, fname)
            elif fname.endswith('.json'):
                warn = QMessageBox()
                warn.setStandardButtons(QMessageBox.Ok)
                warn.setFont(QFont("DejaVu Sans Mono", 12, QtGui.QFont.PreferDefault))
                warn.setText("""Found more than one data file.""")
                warn.exec_()
                return
            else:
                imgs_names.append(os.path.join(dname, fname))
        if data_name == '':
            warn = QMessageBox()
            warn.setStandardButtons(QMessageBox.Ok)
            warn.setFont(QFont("DejaVu Sans Mono", 12, QtGui.QFont.PreferDefault))
            warn.setText("""No data file found.""")
            warn.exec_()
            return

        face_id = self.face_id
        self.face_id += 1

        url = self.facedb_addr + MainWindow.REQ_API_V1_ADD_FACE

        # Send JSON data.
        req = QtNetwork.QNetworkRequest(QtCore.QUrl(url))
        req.setHeader(QtNetwork.QNetworkRequest.ContentTypeHeader,
                      'application/json')
        with open(data_name) as f:
            data = json.load(f)
        data['id'] = '-'
        json_data = {
            'headers': {'src_addr': self.src_addr, 'immed': False},
            'id': face_id,
            'cob': data,
            'imgs_number': len(imgs_names)
        }
        req_data = QtCore.QByteArray()
        req_data.append(json.dumps(json_data, ensure_ascii=False))
        self.network_manager.post(req, req_data)

        # Send all images.
        for img_name in imgs_names:
            req = QtNetwork.QNetworkRequest(QtCore.QUrl(url))
            req.setHeader(QtNetwork.QNetworkRequest.ContentTypeHeader,
                          'application/json')
            with open(img_name, "rb") as f:
                img_buff = f.read()
                b64_img_buff = str(b64encode(img_buff))
                b64_img_buff = b64_img_buff[2:len(b64_img_buff) - 1]
            json_data = {
                'headers': {'src_addr': self.src_addr, 'immed': False},
                'id': face_id,
                'img_buff': b64_img_buff,
            }
            req_data = QtCore.QByteArray()
            req_data.append(json.dumps(json_data, ensure_ascii=False))
            self.network_manager.post(req, req_data)

    def handle_response(self, reply: QtNetwork.QNetworkReply):
        er = reply.error()
        if er == QtNetwork.QNetworkReply.NoError:
            print('ok')
        else:
            print('error')

    def closeEvent(self, event):
        if len(self.sub_windows) != 0:
            warn = QMessageBox()
            warn.setStandardButtons(QMessageBox.Ok)
            warn.setFont(QFont("DejaVu Sans Mono", 12, QtGui.QFont.PreferDefault))
            warn.setText("""You can't quit window, because<br>There are active connections.""")
            warn.exec_()
            event.ignore()
        else:
            event.accept()
            self.app.exit()

    def user_trigger_cb(self):
        p = self.mq.sync_q.get()
        msg = p[0]
        outmq = p[1]

        headers = msg.get('headers')

        id = msg.get('id')

        b64_img_buff = msg.get('img_buff')
        img_buff = b64decode(b64_img_buff)
        buff = BytesIO()
        buff.write(img_buff)
        pix_map = QPixmap()
        pix_map.loadFromData(buff.getvalue())

        faces_data = msg.get('faces_data')

        cur_time = clock()
        nw = NotificationWindow('NW', headers, id, pix_map, faces_data, outmq, cur_time, self)
        self.sub_windows[cur_time] = nw
        nw.show()


class NotificationWindow(QWidget):
    def __init__(self, win_name: str, headers, id, pix_map: QPixmap, faces_data,
                 outmq: janus.Queue, ts: float, parent: MainWindow):
        super().__init__()
        self.win_name = win_name
        self.headers = headers
        self.id = id
        self.pix_map = pix_map
        self.faces_data = faces_data
        self.outmq = outmq
        self.ts = ts
        self.parent = parent
        self.__init_notification_window()

    def __init_notification_window(self):
        self.setFont(QFont("DejaVu Sans Mono", 12, QtGui.QFont.PreferDefault))
        self.setWindowTitle(self.win_name)
        self.setWindowIcon(QIcon(self.pix_map))

        self.grid = QGridLayout()
        self.setLayout(self.grid)

        self.drawing_area = Painter(self.pix_map, self.faces_data, self)
        self.grid.addWidget(self.drawing_area, 0, 0, 5, 1)

        self.submit_btn = PushButtonOnce('submit', self)
        self.submit_btn.setToolTip("""'submit' button sends all faces data to server.<br>
        You can't undo it.""")
        self.submit_btn.setCheckable(True)
        self.submit_btn.clicked.connect(self.submit_btn_clicked)
        self.grid.addWidget(self.submit_btn, 0, 1)

        self.recognize_again_btn = PushButtonOnce('recognize again', self)
        self.recognize_again_btn.setToolTip("""'recognize again' button asks server to recognize all faces again.<br>
        It is useful, when You've removed (added) some face data from (to) image.""")
        self.recognize_again_btn.setCheckable(True)
        self.recognize_again_btn.clicked.connect(self.recognize_again_btn_clicked)
        self.grid.addWidget(self.recognize_again_btn, 1, 1)

        self.cancel_btn = PushButtonOnce('cancel', self)
        self.cancel_btn.setToolTip("""'cancel' button drops image<br>
        (its faces data will not be saved).<br>
        You can't undo it.""")
        self.cancel_btn.setCheckable(True)
        self.cancel_btn.clicked.connect(self.cancel_btn_clicked)
        self.grid.addWidget(self.cancel_btn, 2, 1)

        self.save_data_btn = PushButtonOnce('save data', self)
        self.save_data_btn.setToolTip("""'save data' button saves image and its faces data to selected path<br>
        (image will be saved as '/path.png', faces data - as '/path.json'""")
        self.save_data_btn.clicked.connect(self.save_data_btn_clicked)
        self.grid.addWidget(self.save_data_btn, 3, 1)

        self.faces_widget = FaceTabsWidget(self.faces_data)
        for i in range(len(self.faces_data)):
            face_tab = FaceTab(i, self.faces_data[i], self.faces_widget)
            self.faces_widget.addTab(face_tab, str(face_tab.index))
        self.grid.addWidget(self.faces_widget, 4, 1)

    def save_data_btn_clicked(self):
        dname = QFileDialog.getSaveFileName(self, 'Save data', str(Path.home()))[0]
        if os.path.exists(dname):
            warn = QMessageBox()
            warn.setStandardButtons(QMessageBox.Ok)
            warn.setFont(QFont("DejaVu Sans Mono", 12, QtGui.QFont.PreferDefault))
            warn.setText("""Choose non-existing folder.""")
            return
        os.mkdir(dname)
        img_name = os.path.join(dname, 'img.png')
        self.pix_map.save(img_name)
        data_name = os.path.join(dname, 'faces.json')
        with open(data_name, 'w') as out:
            json.dump({'faces_data': self.faces_data}, out,
                      ensure_ascii=False, indent=4, sort_keys=True)

    def update_faces_data(self):
        for i in range(len(self.faces_data)):
            self.faces_data[i]['cob']['name'] = self.faces_widget.widget(i).name.text()
            self.faces_data[i]['cob']['patronymic'] = self.faces_widget.widget(i).patronymic.text()
            self.faces_data[i]['cob']['surname'] = self.faces_widget.widget(i).surname.text()
            self.faces_data[i]['cob']['passport'] = self.faces_widget.widget(i).passport.text()
            self.faces_data[i]['cob']['phone_num'] = self.faces_widget.widget(i).phone_num.text()

    def submit_btn_clicked(self):
        self.submit_btn.setChecked(True)
        if not self.submit_btn.first_time or \
                self.recognize_again_btn.isChecked() or \
                self.cancel_btn.isChecked():
            return
        self.submit_btn.first_time = False
        self.update_faces_data()
        msg = {
            'headers': {'src_addr': '', 'immed': False},
            'cmd': 'submit',
            'id': self.id,
            'faces_data': self.faces_data
        }
        self.outmq.sync_q.put(msg)
        self.parent.sub_windows.pop(self.ts)

    def recognize_again_btn_clicked(self):
        self.recognize_again_btn.setChecked(True)
        if not self.recognize_again_btn.first_time or \
                self.submit_btn.isChecked() or \
                self.cancel_btn.isChecked():
            return
        self.recognize_again_btn.first_time = False
        self.update_faces_data()
        msg = {
            'headers': {'src_addr': '', 'immed': False},
            'cmd': 'recognize_again',
            'id': self.id,
            'faces_data': self.faces_data
        }
        self.outmq.sync_q.put(msg)
        self.parent.sub_windows.pop(self.ts)

    def cancel_btn_clicked(self):
        self.cancel_btn.setChecked(True)
        if not self.cancel_btn.first_time or \
                self.submit_btn.isChecked() or \
                self.recognize_again_btn.isChecked():
            return
        self.cancel_btn.first_time = False
        msg = {
            'headers': {'src_addr': '', 'immed': False},
            'cmd': 'cancel',
            'id': self.id
        }
        self.outmq.sync_q.put(msg)
        self.parent.sub_windows.pop(self.ts)

    def closeEvent(self, event):
        if self.submit_btn.first_time and \
                self.recognize_again_btn.first_time and \
                self.cancel_btn.first_time:
            warn = QMessageBox()
            warn.setStandardButtons(QMessageBox.Ok)
            warn.setFont(QFont("DejaVu Sans Mono", 12, QtGui.QFont.PreferDefault))
            warn.setText("""You can't quit window without pressing<br>
            'submit', 'recognize again' or 'cancel' button.""")
            warn.exec_()
            event.ignore()
        else:
            event.accept()


class Painter(QWidget):
    def __init__(self, pix_map: QPixmap, faces_data, parent: NotificationWindow):
        super().__init__()
        self.pix_map = pix_map
        self.faces_data = faces_data
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
            self.faces_data.append({
                'box': [top, right, bottom, left],
                'cob': {
                    'id': '-',
                    'name': '-',
                    'patronymic': '-',
                    'surname': '-',
                    'passport': '-',
                    'sex': '-',
                    'phone_num': '-'
                }
            })
            face_tab = FaceTab(len(self.faces_data) - 1, self.faces_data[-1], self.parent.faces_widget)
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
        for i in range(len(self.faces_data)):
            fb = FaceBox(self.faces_data[i].get('box'))
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


class InfoWidget(QWidget):
    def __init__(self, logo_path: str, w_size, guide_text: str):
        super().__init__()
        self.logo_path = logo_path
        self.guide_text = guide_text
        self.__init_main_widget(w_size)

    def __init_main_widget(self, w_size):
        self.grid = QGridLayout()
        self.setLayout(self.grid)
        positions = [(0, 0), (1, 0)]

        logo = QLabel()
        logo.setAlignment(Qt.AlignHCenter | Qt.AlignVCenter)
        pix_map = QPixmap(self.logo_path)
        sh = int(w_size[0] * 0.5)
        pix_map.scaledToHeight(sh)
        logo.setPixmap(pix_map)
        self.logo = logo
        self.grid.addWidget(self.logo, *positions[0])

        guide = QLabel()
        guide.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        guide.setOpenExternalLinks(True)
        guide.setWordWrap(True)
        guide.setText(self.guide_text)
        self.guide = guide
        self.grid.addWidget(self.guide, *positions[1])


class GUI:
    APP_NAME = 'ControlPanel'
    STATIC_PATH = '/home/mikhail/Python/controlpanel/static/'
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

    def __init__(self, mq: janus.Queue, src_addr: str, facedb_addr: str):
        app = QApplication(sys.argv)
        self.app = app
        self.mq = mq
        self.main_window = MainWindow(self.app, self.mq, GUI.APP_NAME, GUI.STATIC_PATH,
                                      GUI.WIDTH_COEF, GUI.HEIGHT_COEF, GUI.GUIDE_TEXT, src_addr, facedb_addr)
        self.facedb_addr = facedb_addr
        self.src_addr = src_addr

    def notify_gui(self):
        self.main_window.user_trigger.sig.emit()

    def show(self):
        self.app.exec_()


class HTTPServerCFG:
    def __init__(self, cfg: dict):
        self.name = cfg['name']
        self.socket = cfg['socket']
        self.write_timeout_ms = cfg['write_timeout_ms']
        self.read_timeout_ms = cfg['read_timeout_ms']
        self.immed_resp = cfg['immed_resp']
        self.req_max_size = cfg['req_max_size']
        self.key_path = cfg['key_path']
        self.crt_path = cfg['crt_path']


class FaceDBCFG:
    def __init__(self, cfg: dict):
        self.addr = cfg['addr']


class CFG:
    def __init__(self, fcfg: dict):
        self.http_server_cfg = HTTPServerCFG(fcfg['http_server'])
        self.facedb_cfg = FaceDBCFG(fcfg['facedb'])


class HTTPServer:
    """HTTPServer class handles notifications about processed images."""

    STATUS_BAD_REQUEST = 400
    STATUS_INTERNAL_SERVER_ERROR = 500

    API_V1_NOTIFY_IMG = '/api/v1/notify_img'
    API_V1_CONFIRM_IMG = '/api/v1/confirm_img'

    def __init__(self, cfg: CFG, loop: asyncio.BaseEventLoop, gui: GUI):
        self.cfg = cfg
        app = web.Application(client_max_size=self.cfg.http_server_cfg.req_max_size)
        app.add_routes([web.put(HTTPServer.API_V1_NOTIFY_IMG, self.notify_img_handler),
                        web.put(HTTPServer.API_V1_CONFIRM_IMG, self.confirm_img_handler)])
        self.app = app
        if self.cfg.http_server_cfg.key_path != '' and self.cfg.http_server_cfg.crt_path != '':
            self.src_addr = 'https://' + self.cfg.http_server_cfg.name
        else:
            self.src_addr = 'http://' + self.cfg.http_server_cfg.name

        self.loop = loop
        self.gui = gui

    def run(self):
        asyncio.set_event_loop(self.loop)
        runner = self.app.make_handler()

        conn_str = self.cfg.http_server_cfg.socket
        is_ip_port = match(r'(\d)+\.(\d)+\.(\d)+\.(\d)+:(\d)+', conn_str) is not None
        if self.cfg.http_server_cfg.crt_path != '' and self.cfg.http_server_cfg.key_path != '':
            ssl_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
            ssl_context.load_cert_chain(self.cfg.http_server_cfg.crt_path,
                                        self.cfg.http_server_cfg.key_path)
        else:
            ssl_context = None
        if is_ip_port:
            conn_data = conn_str.split(':')
            host = conn_data[0]
            port = int(conn_data[1])
            if ssl_context is not None:
                srv = self.loop.create_server(runner, host=host, port=port, ssl=ssl_context)
            else:
                srv = self.loop.create_server(runner, host=host, port=port, ssl=ssl_context)
        else:
            path = conn_str
            if ssl_context is not None:
                srv = self.loop.create_unix_connection(runner, path, ssl=ssl_context)
            else:
                srv = self.loop.create_unix_connection(runner, path, ssl=ssl_context)

        self.loop.run_until_complete(srv)
        self.loop.run_forever()

    RESP_API_V1_PUT_CONTROL = '/api/v1/put_control'

    async def notify_img_handler(self, req: web.Request) -> web.Response:
        try:
            body = await req.json()
            headers = body['headers']
            addr = headers['src_addr']
            req_id = body['id']
            b64_img_buff = body['img_buff']
            faces = body['faces_data']
        except KeyError:
            return web.json_response({
                'headers': {'src_addr': self.src_addr, 'immed': False},
                'id': req_id,
                'error': True,
                'error_info': 'invalid request data'
            }, status=HTTPServer.STATUS_BAD_REQUEST)

        msg = body
        outmq = janus.Queue(loop=self.loop)
        p = (msg, outmq)
        self.gui.mq.sync_q.put(p)
        self.gui.notify_gui()
        if self.cfg.http_server_cfg.immed_resp:
            asyncio.run_coroutine_threadsafe(self.notify_img_create_resp(outmq), loop=self.loop)
            return web.json_response({'headers': {'src_addr': '', 'immed': True}})

        msg = await outmq.async_q.get()
        return web.json_response(msg)

    async def notify_img_create_resp(self, outmq: janus.Queue):
        data = await outmq.async_q.get()
        addr = data[0]
        msg = data[1]
        async with ClientSession(
                json_serialize=json.dumps) as session:
            await session.put(addr + HTTPServer.RESP_API_V1_PUT_CONTROL, json=msg)

    async def confirm_img_handler(self, req: web.Request) -> web.Response:
        pass

    async def confirm_img_create_resp(self):
        pass


DESC_STR = r"""FaceRecognition is a simple script, that finds all faces in image
and returns their coordinates and features vectors.
"""


def parse_args():
    parser = argparse.ArgumentParser(prog='FaceRecognition',
                                     formatter_class=argparse.RawDescriptionHelpFormatter,
                                     description=DESC_STR)
    parser.add_argument('-v', '--version', action='version', version='%(prog)s v0.1')
    parser.add_argument('-c', '--config', type=str, default='',
                        help='path to yaml config file')

    args = parser.parse_args()

    return args


def main():
    args = parse_args()
    with open(args.config, 'r') as stream:
        fcfg = yaml.safe_load(stream)
        cfg = CFG(fcfg)

    loop = asyncio.new_event_loop()
    mq = janus.Queue(loop=loop)
    src_addr = 'http://' + cfg.http_server_cfg.socket
    gui = GUI(mq, src_addr, cfg.facedb_cfg.addr)
    http_server = HTTPServer(cfg, loop, gui)
    t = threading.Thread(target=http_server.run, name='http_server')
    t.daemon = True
    t.start()
    gui.show()


if __name__ == '__main__':
    main()

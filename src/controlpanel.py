#!/usr/bin/python3
# -*- coding: utf-8 -*-

import argparse
import asyncio
import datetime
import json
import os
import ssl
import sys
import threading
import uuid
from base64 import b64encode, b64decode
from io import BytesIO
from pathlib import Path
from time import clock

import janus
import yaml
from PIL import Image
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
    def __init__(self, image_control_objects, parent):
        super().__init__()
        self.parent = parent
        self.image_control_objects = image_control_objects
        self.setFont(QFont("DejaVu Sans Mono", 12, QtGui.QFont.PreferDefault))


class PushButtonOnce(QPushButton):
    def __init__(self, name: str, parent):
        super().__init__(name, parent)
        self.first_time = True


class FaceTab(QWidget):
    PASSPORT_TITLE = 'passport'
    SURNAME_TITLE = 'surname'
    NAME_TITLE = 'name'
    PATRONYMIC_TITLE = 'patronymic'
    SEX_TITLE = 'sex'
    BIRTHDATE_TITLE = 'birthdate'
    PHONE_NUM_TITLE = 'phone_num'
    EMAIL_TITLE = 'email'
    ADDRESS_TITLE = 'address'

    def __init__(self, index, image_control_object, parent: FaceTabsWidget):
        super().__init__()
        self.index = index
        self.image_control_object = image_control_object
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
                     ((5, 0), (5, 1)),
                     ((6, 0), (6, 1)),
                     ((7, 0), (7, 1)),
                     ((8, 0), (8, 1)),
                     (9, 0)]

        passport_title = QLabel()
        passport_title.setText(FaceTab.PASSPORT_TITLE)
        self.grid.addWidget(passport_title, *positions[0][0])
        self.passport = QLineEdit()
        self.passport.setText(self.image_control_object['control_object']['passport'])
        self.grid.addWidget(self.passport, *positions[0][1])

        surname_title = QLabel()
        surname_title.setText(FaceTab.SURNAME_TITLE)
        self.grid.addWidget(surname_title, *positions[1][0])
        self.surname = QLineEdit()
        self.surname.setText(self.image_control_object['control_object']['surname'])
        self.grid.addWidget(self.surname, *positions[1][1])

        name_title = QLabel()
        name_title.setText(FaceTab.NAME_TITLE)
        self.grid.addWidget(name_title, *positions[2][0])
        self.name = QLineEdit()
        self.name.setText(self.image_control_object['control_object']['name'])
        self.grid.addWidget(self.name, *positions[2][1])

        patronymic_title = QLabel()
        patronymic_title.setText(FaceTab.PATRONYMIC_TITLE)
        self.grid.addWidget(patronymic_title, *positions[3][0])
        self.patronymic = QLineEdit()
        self.patronymic.setText(self.image_control_object['control_object']['patronymic'])
        self.grid.addWidget(self.patronymic, *positions[3][1])

        sex_title = QLabel()
        sex_title.setText(FaceTab.SEX_TITLE)
        self.grid.addWidget(sex_title, *positions[4][0])
        self.sex = QLineEdit()
        self.sex.setText(self.image_control_object['control_object']['sex'])
        self.grid.addWidget(self.sex, *positions[4][1])

        birthdate_title = QLabel()
        birthdate_title.setText(FaceTab.BIRTHDATE_TITLE)
        self.grid.addWidget(birthdate_title, *positions[5][0])
        self.birthdate = QLineEdit()
        self.birthdate.setText(self.image_control_object['control_object']['birthdate'])
        self.grid.addWidget(self.birthdate, *positions[5][1])

        phone_num_title = QLabel()
        phone_num_title.setText(FaceTab.PHONE_NUM_TITLE)
        self.grid.addWidget(phone_num_title, *positions[6][0])
        self.phone_num = QLineEdit()
        self.phone_num.setText(self.image_control_object['control_object']['phone_num'])
        self.grid.addWidget(self.phone_num, *positions[6][1])

        email_title = QLabel()
        email_title.setText(FaceTab.EMAIL_TITLE)
        self.grid.addWidget(email_title, *positions[7][0])
        self.email = QLineEdit()
        self.email.setText(self.image_control_object['control_object']['email'])
        self.grid.addWidget(self.email, *positions[7][1])

        address_title = QLabel()
        address_title.setText(FaceTab.ADDRESS_TITLE)
        self.grid.addWidget(address_title, *positions[8][0])
        self.address = QLineEdit()
        self.address.setText(self.image_control_object['control_object']['address'])
        self.grid.addWidget(self.address, *positions[8][1])

        self.delete_btn = QPushButton('delete', self)
        self.delete_btn.setToolTip("""'delete' button removes this face from image.""")
        self.delete_btn.clicked.connect(self.delete_btn_clicked)
        self.grid.addWidget(self.delete_btn, *positions[9])

    def delete_btn_clicked(self):
        self.parent.removeTab(self.index)
        del self.parent.image_control_objects[self.index]
        for i in range(self.parent.count()):
            w = self.parent.widget(i)
            w.index = i
            self.parent.setTabText(w.index, str(w.index))
        self.parent.parent.drawing_area.update()


class MainWindow(QMainWindow):
    def __init__(self, app: QApplication, mq: janus.Queue, app_name: str,
                 static_path: str, width_coef: float, height_coef: float, guide_text: str, src_addr: str,
                 facedb_addr: str):
        super().__init__()

        self.app = app
        self.mq = mq

        self.awaiting_control_objects = {}
        self.awaiting_controls = {}

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

    REQ_API_V1_PUT_IMAGE = '/api/v1/put_image'

    def __find_action_started(self):
        fname = QFileDialog.getOpenFileName(self, 'Choose image', str(Path.home()))[0]
        if not os.path.isfile(fname):
            warn = QMessageBox()
            warn.setStandardButtons(QMessageBox.Ok)
            warn.setFont(QFont("DejaVu Sans Mono", 12, QtGui.QFont.PreferDefault))
            warn.setText("""You should choose image.""")
            warn.exec_()
            return

        url = self.facedb_addr + MainWindow.REQ_API_V1_PUT_IMAGE
        req = QtNetwork.QNetworkRequest(QtCore.QUrl(url))
        req.setHeader(QtNetwork.QNetworkRequest.ContentTypeHeader,
                      'application/json')
        try:
            img = Image.open(fname)
            bytes_io = BytesIO()
            img.save(bytes_io, format='PNG')
            img_buff = str(b64encode(bytes_io.getvalue()))
            img_buff = img_buff[2:len(img_buff) - 1]
        except Exception:
            warn = QMessageBox()
            warn.setStandardButtons(QMessageBox.Ok)
            warn.setFont(QFont("DejaVu Sans Mono", 12, QtGui.QFont.PreferDefault))
            warn.setText("""Chosen file is not an image. Dropping request.""")
            warn.exec_()
            return

        find_face_id = str(uuid.uuid4())
        self.awaiting_controls[find_face_id] = {
            'ts': datetime.datetime.now(),
            'fname': fname
        }
        json_data = {
            'header': {'src_addr': self.src_addr, 'uuid': find_face_id},
            'img_buff': img_buff,
        }
        req_data = QtCore.QByteArray()
        req_data.append(json.dumps(json_data, ensure_ascii=False))
        self.network_manager.put(req, req_data)

    REQ_API_V1_ADD_CONTROL_OBJECT = '/api/v1/add_control_object'

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

        url = self.facedb_addr + MainWindow.REQ_API_V1_ADD_CONTROL_OBJECT

        img_buffs = []
        for img_name in imgs_names:
            try:
                img = Image.open(img_name)
                bytes_io = BytesIO()
                img.save(bytes_io, format='PNG')
                img_buff = str(b64encode(bytes_io.getvalue()))
                img_buff = img_buff[2:len(img_buff) - 1]
            except Exception:
                warn = QMessageBox()
                warn.setStandardButtons(QMessageBox.Ok)
                warn.setFont(QFont("DejaVu Sans Mono", 12, QtGui.QFont.PreferDefault))
                warn.setText('File "%s" is not an image. Dropping request.' % img_name)
                warn.exec_()
                return
            img_buffs.append(img_buff)

        add_face_uuid = str(uuid.uuid4())
        self.awaiting_control_objects[add_face_uuid] = {
            'ts': datetime.datetime.now(),
            'dname': dname
        }

        # Send JSON data.

        req = QtNetwork.QNetworkRequest(QtCore.QUrl(url))
        req.setHeader(QtNetwork.QNetworkRequest.ContentTypeHeader,
                      'application/json')
        with open(data_name) as f:
            data = json.load(f)
        data['id'] = '-'
        json_data = {
            'header': {'src_addr': self.src_addr, 'uuid': add_face_uuid},
            'control_object_part': {
                'control_object': data,
                'images_num': len(imgs_names)
            },
            'image_part': None
        }
        req_data = QtCore.QByteArray()
        req_data.append(json.dumps(json_data, ensure_ascii=False))
        self.network_manager.post(req, req_data)

        # Send all images.
        for i in range(len(img_buffs)):
            req = QtNetwork.QNetworkRequest(QtCore.QUrl(url))
            req.setHeader(QtNetwork.QNetworkRequest.ContentTypeHeader,
                          'application/json')
            json_data = {
                'header': {'src_addr': self.src_addr, 'uuid': add_face_uuid},
                'control_object_part': None,
                'image_part': {
                    'curr_num': i,
                    'img_buff': img_buffs[i],
                    'facebox': None
                }
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
        if p[0] == 'notify_control':
            self.on_notify_control(p)
        elif p[0] == 'notify_add_control_object':
            self.on_notify_add_control_object(p)

    def on_notify_control(self, p):
        msg = p[1]
        outmq = p[2]

        header = msg.get('header')

        req_uuid = header.get('uuid')

        img_buff = msg.get('img_buff')
        img_buff = b64decode(img_buff)
        buff = BytesIO()
        buff.write(img_buff)
        img_buff = buff
        pix_map = QPixmap()
        pix_map.loadFromData(img_buff.getvalue())

        image_control_objects = msg.get('image_control_objects')
        if self.awaiting_controls.get(req_uuid) is not None:
            aw_control = self.awaiting_controls.pop(req_uuid)
            win_name = '"%s" in %s' % (aw_control['fname'], (datetime.datetime.now() - aw_control['ts']))
        else:
            win_name = 'Unknown new image'
        cur_time = clock()
        nw = NotificationWindow(self.src_addr, win_name, header, req_uuid, pix_map, image_control_objects, outmq, cur_time,
                                self)
        self.sub_windows[cur_time] = nw
        nw.show()

    def on_notify_add_control_object(self, p):
        notify = QMessageBox()
        notify.setStandardButtons(QMessageBox.Ok)
        notify.setFont(QFont("DejaVu Sans Mono", 12, QtGui.QFont.PreferDefault))
        req_uuid = p[1].get('header').get('uuid')
        if self.awaiting_control_objects.get(req_uuid) is not None:
            aw_cob = self.awaiting_control_objects.pop(req_uuid)
            notify.setText('"AddControlObject" request for folder "%s" in %s seconds' %
                           (aw_cob['dname'], (datetime.datetime.now() - aw_cob['ts'])))
        else:
            notify.setText('Unknown "AddControlObject" request was processed')
        notify.exec_()

class NotificationWindow(QWidget):
    def __init__(self, src_addr, win_name: str, header, uuid, pix_map: QPixmap, image_control_objects,
                 outmq: janus.Queue, ts: float, parent: MainWindow):
        super().__init__()
        self.src_addr = src_addr
        self.win_name = win_name
        self.header = header
        self.uuid = uuid
        self.pix_map = pix_map
        self.image_control_objects = image_control_objects
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

        self.drawing_area = Painter(self.pix_map, self.size().width(), self.size().height(), self.image_control_objects,
                                    self)
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

        self.faces_widget = FaceTabsWidget(self.image_control_objects, self)
        for i in range(len(self.image_control_objects)):
            face_tab = FaceTab(i, self.image_control_objects[i], self.faces_widget)
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
            json.dump({'image_control_objects': self.image_control_objects}, out,
                      ensure_ascii=False, indent=4, sort_keys=True)

    def update_image_control_objects(self):
        for i in range(len(self.image_control_objects)):
            self.image_control_objects[i]['control_object']['passport'] = self.faces_widget.widget(i).passport.text()
            self.image_control_objects[i]['control_object']['surname'] = self.faces_widget.widget(i).surname.text()
            self.image_control_objects[i]['control_object']['name'] = self.faces_widget.widget(i).name.text()
            self.image_control_objects[i]['control_object']['patronymic'] = self.faces_widget.widget(
                i).patronymic.text()
            self.image_control_objects[i]['control_object']['sex'] = self.faces_widget.widget(i).sex.text()
            self.image_control_objects[i]['control_object']['birthdate'] = self.faces_widget.widget(i).birthdate.text()
            self.image_control_objects[i]['control_object']['phone_num'] = self.faces_widget.widget(i).phone_num.text()
            self.image_control_objects[i]['control_object']['email'] = self.faces_widget.widget(i).email.text()
            self.image_control_objects[i]['control_object']['address'] = self.faces_widget.widget(i).address.text()

    def submit_btn_clicked(self):
        self.submit_btn.setChecked(True)
        if not self.submit_btn.first_time or \
                self.recognize_again_btn.isChecked() or \
                self.cancel_btn.isChecked():
            return
        self.submit_btn.first_time = False
        self.update_image_control_objects()
        msg = {
            'header': {'src_addr': self.src_addr, 'uuid': self.uuid},
            'command': 'submit',
            'image_control_objects': self.image_control_objects
        }
        self.outmq.sync_q.put((self.header['src_addr'], msg))
        self.parent.sub_windows.pop(self.ts)

    def recognize_again_btn_clicked(self):
        self.recognize_again_btn.setChecked(True)
        if not self.recognize_again_btn.first_time or \
                self.submit_btn.isChecked() or \
                self.cancel_btn.isChecked():
            return
        self.recognize_again_btn.first_time = False
        self.update_image_control_objects()
        msg = {
            'header': {'src_addr': self.src_addr, 'uuid': self.uuid},
            'command': 'process_again',
            'image_control_objects': self.image_control_objects
        }
        self.outmq.sync_q.put((self.header['src_addr'], msg))
        self.parent.sub_windows.pop(self.ts)

    def cancel_btn_clicked(self):
        self.cancel_btn.setChecked(True)
        if not self.cancel_btn.first_time or \
                self.submit_btn.isChecked() or \
                self.recognize_again_btn.isChecked():
            return
        self.cancel_btn.first_time = False
        msg = {
            'header': {'src_addr': self.src_addr, 'uuid': self.uuid},
            'command': 'cancel',
        }
        self.outmq.sync_q.put((self.header['src_addr'], msg))
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
    def __init__(self, pix_map: QPixmap, max_width, max_height, image_control_objects, parent: NotificationWindow):
        super().__init__()
        width_coef = pix_map.width() / max_width
        height_coef = pix_map.height() / max_height
        if (width_coef > height_coef) and (height_coef >= 1.0):
            self.coef = height_coef
        else:
            self.coef = width_coef
        self.setFixedSize(int(pix_map.width() / self.coef), int(pix_map.height() / self.coef))
        self.pix_map = pix_map.scaled(int(pix_map.width() / self.coef),
                                      int(pix_map.height() / self.coef))
        self.image_control_objects = image_control_objects
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
            self.image_control_objects.append({
                'facebox': [int(self.coef * top),
                            int(self.coef * right),
                            int(self.coef * bottom),
                            int(self.coef * left)],
                'control_object': {
                    'id': '-',
                    'passport': '-',
                    'surname': '-',
                    'name': '-',
                    'patronymic': '-',
                    'sex': '-',
                    'birthdate': '-',
                    'phone_num': '-',
                    'email': '-',
                    'address': '-'
                }
            })
            face_tab = FaceTab(len(self.image_control_objects) - 1, self.image_control_objects[-1],
                               self.parent.faces_widget)
            self.parent.faces_widget.addTab(face_tab, str(face_tab.index))
        self.update()
        self.pressed_coords = None
        self.released_coords = None

    def __is_point_in_img(self, p: QPoint) -> bool:
        if (p.x() >= 0) and (p.x() < self.width()) and \
                (p.y() >= 0) and (p.y() < self.height()):
            return True
        return False

    def paintEvent(self, event: QPaintEvent):
        painter = QPainter(self)
        painter.drawPixmap(QRect(0, 0, self.pix_map.width(), self.pix_map.height()), self.pix_map)
        painter.setPen(QPen(Qt.green, 3))
        painter.setFont(QFont("DejaVu Sans Mono", 18, QtGui.QFont.PreferDefault))
        for i in range(len(self.image_control_objects)):
            fb = FaceBox(self.image_control_objects[i].get('facebox'))
            rect = QRect(int(fb.right / self.coef),
                         int(fb.top / self.coef),
                         int((fb.left - fb.right) / self.coef),
                         int((fb.bottom - fb.top) / self.coef))
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
        self.addr = cfg['addr']
        self.port = cfg['port']
        self.write_timeout_ms = cfg['write_timeout_ms']
        self.read_timeout_ms = cfg['read_timeout_ms']
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

    INVALID_REQUEST_METHOD_CODE = -1
    CORRUPTED_BODY_CODE = -2
    UNABLE_TO_ENQUEUE = -3
    UNABLE_TO_SEND = -4
    INTERNAL_SERVER_ERROR = -5

    STATUS_BAD_REQUEST = 400
    STATUS_INTERNAL_SERVER_ERROR = 500

    API_BASE = '/api/v1'
    API_NOTIFY_CONTROL = API_BASE + '/notify_control'
    API_NOTIFY_ADD_CONTROL_OBJECT = API_BASE + '/notify_add_control_object'

    def __init__(self, cfg: CFG, src_addr, loop: asyncio.BaseEventLoop, gui: GUI):
        self.src_addr = src_addr
        self.cfg = cfg
        app = web.Application(client_max_size=self.cfg.http_server_cfg.req_max_size)
        app.add_routes([web.put(HTTPServer.API_NOTIFY_CONTROL, self.notify_control),
                        web.put(HTTPServer.API_NOTIFY_ADD_CONTROL_OBJECT, self.notify_add_control_object)])
        self.app = app

        self.loop = loop
        self.gui = gui

    def run(self):
        asyncio.set_event_loop(self.loop)
        runner = self.app.make_handler()

        if self.cfg.http_server_cfg.crt_path != '' and self.cfg.http_server_cfg.key_path != '':
            ssl_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
            ssl_context.load_cert_chain(self.cfg.http_server_cfg.crt_path,
                                        self.cfg.http_server_cfg.key_path)
        else:
            ssl_context = None

        if ssl_context is not None:
            srv = self.loop.create_server(runner,
                                          host=self.cfg.http_server_cfg.addr,
                                          port=self.cfg.http_server_cfg.port,
                                          ssl=ssl_context)
        else:
            srv = self.loop.create_server(runner,
                                          host=self.cfg.http_server_cfg.addr,
                                          port=self.cfg.http_server_cfg.port,
                                          ssl=ssl_context)

        self.loop.run_until_complete(srv)
        self.loop.run_forever()

    RESP_API_V1_PUT_CONTROL = '/api/v1/put_control'

    async def notify_control(self, req: web.Request) -> web.Response:
        req_uuid = ''
        try:
            body = await req.json()
            header = body['header']
            addr = header['src_addr']
            req_uuid = header['uuid']
            img_buff = body['img_buff']
            image_control_objects = body['image_control_objects']
        except KeyError:
            return web.json_response({
                'headers': {'src_addr': self.src_addr, 'uuid': req_uuid},
                'error_data': {
                    'error_code': HTTPServer.CORRUPTED_BODY_CODE,
                    'error_info': 'corrupted request body',
                    'error_text': 'unable to read request body'
                }
            }, status=HTTPServer.STATUS_BAD_REQUEST)

        msg = body
        outmq = janus.Queue(loop=self.loop)
        p = ('notify_control', msg, outmq)
        self.gui.mq.sync_q.put(p)
        self.gui.notify_gui()

        asyncio.run_coroutine_threadsafe(self.notify_control_create_resp(outmq), loop=self.loop)
        return web.json_response({'headers': {'src_addr': self.src_addr, 'uuid': req_uuid}})

    async def notify_control_create_resp(self, outmq: janus.Queue):
        data = await outmq.async_q.get()
        addr = data[0]
        msg = data[1]
        async with ClientSession(
                json_serialize=json.dumps) as session:
            await session.put(addr + HTTPServer.RESP_API_V1_PUT_CONTROL, json=msg)

    async def notify_add_control_object(self, req: web.Request) -> web.Response:
        req_uuid = ''
        try:
            body = await req.json()
            header = body['header']
            addr = header['src_addr']
            req_uuid = header['uuid']
        except KeyError:
            return web.json_response({
                'headers': {'src_addr': self.src_addr, 'uuid': req_uuid},
                'error_data': {
                    'error_code': HTTPServer.CORRUPTED_BODY_CODE,
                    'error_info': 'corrupted request body',
                    'error_text': 'unable to read request body'
                }
            }, status=HTTPServer.STATUS_BAD_REQUEST)

        msg = body
        p = ('notify_add_control_object', msg)
        self.gui.mq.sync_q.put(p)
        self.gui.notify_gui()

        return web.json_response({'headers': {'src_addr': self.src_addr, 'uuid': req_uuid}})


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
    if cfg.http_server_cfg.key_path != '' and cfg.http_server_cfg.crt_path != '':
        src_addr = 'https://' + cfg.http_server_cfg.addr + ':' + str(cfg.http_server_cfg.port)
    else:
        src_addr = 'http://' + cfg.http_server_cfg.addr + ':' + str(cfg.http_server_cfg.port)
    gui = GUI(mq, src_addr, cfg.facedb_cfg.addr)
    http_server = HTTPServer(cfg, src_addr, loop, gui)
    t = threading.Thread(target=http_server.run, name='http_server')
    t.daemon = True
    t.start()
    gui.show()


if __name__ == '__main__':
    main()

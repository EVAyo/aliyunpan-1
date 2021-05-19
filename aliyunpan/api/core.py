import sys
import time
import requests
import func_timeout
from pathlib import Path
from collections.abc import Iterable
from aliyunpan.api.req import *
from aliyunpan.api.type import UserInfo
from aliyunpan.api.utils import *
from aliyunpan.common import *
from aliyunpan.exceptions import InvalidRefreshToken, AliyunpanException

__all__ = ['AliyunPan']


class AliyunPan(object):

    def __init__(self, refresh_token: str = None):
        self._req = Req()
        self._req.disk = self
        self._user_info = None
        self._access_token = None
        self._drive_id = None
        self._refresh_token = refresh_token
        self._access_token_gen_ = self._access_token_gen()
        self._drive_id_gen_ = self._drive_id_gen()
        self._chunk_size = 524288
        self._print = Printer()

    refresh_token = property(lambda self: self._refresh_token,
                             lambda self, value: setattr(self, '_refresh_token', value))
    access_token = property(lambda self: next(self._access_token_gen_),
                            lambda self, value: setattr(self, '_access_token', value))
    drive_id = property(lambda self: next(self._drive_id_gen_),
                        lambda self, value: setattr(self, '_drive_id', value))

    def login(self, username: str, password: str):
        """
        登录api
        https://github.com/zhjc1124/aliyundrive
        :param username:
        :param password:
        :return:
        """
        password2 = encrypt(password)
        LOGIN = {
            'method': 'POST',
            'url': 'https://passport.aliyundrive.com/newlogin/login.do',
            'data': {
                'loginId': username,
                'password2': password2,
                'appName': 'aliyun_drive',
            }
        }
        logger.info('Logging in.')
        r = self._req.req(**LOGIN, access_token=False)
        if 'bizExt' in r.json()['content']['data']:
            data = parse_biz_ext(r.json()['content']['data']['bizExt'])
            logger.debug(data)
            access_token = data['pds_login_result']['accessToken']
            self._access_token = access_token
            GLOBAL_VAR.access_token = access_token
            refresh_token = data['pds_login_result']['refreshToken']
            self._refresh_token = refresh_token
            GLOBAL_VAR.refresh_token = refresh_token
            drive_id = data['pds_login_result']['defaultDriveId']
            self._drive_id = drive_id
            GLOBAL_VAR.drive_id = drive_id
            return self._refresh_token
        return False

    def get_file_list(self, parent_file_id: str = 'root', next_marker: str = None) -> dict:
        """
        获取文件列表
        :param parent_file_id:
        :param next_marker:
        :return:
        """
        url = 'https://api.aliyundrive.com/v2/file/list'
        json = {"drive_id": self.drive_id, "parent_file_id": parent_file_id, 'fields': '*', 'marker': next_marker}
        logger.info(f'Get the list of parent_file_id {parent_file_id}.')
        r = self._req.post(url, json=json)
        logger.debug(r.status_code)
        if 'items' not in r.json():
            return False
        file_list = r.json()['items']
        if 'next_marker' in r.json() and r.json()['next_marker'] and next_marker != r.json()['next_marker']:
            file_list.extend(self.get_file_list(parent_file_id, r.json()['next_marker']))
        return file_list

    def delete_file(self, file_id: str):
        """
        删除文件
        :param file_id:
        :return:
        """
        url = 'https://api.aliyundrive.com/v2/batch'
        json = {'requests': [{'body': {'drive_id': self.drive_id, 'file_id': file_id},
                              'headers': {'Content-Type': 'application/json'},
                              'id': file_id, 'method': 'POST',
                              'url': '/recyclebin/trash'}], 'resource': 'file'}
        logger.info(f'Delete file {file_id}.')
        r = self._req.post(url, json=json)
        logger.debug(r.text)
        if r.status_code == 200:
            return r.json()['responses'][0]['id']
        return False

    def move_file(self, file_id: str, parent_file_id: str):
        """
        移动文件
        :param file_id:
        :param parent_file_id:
        :return:
        """
        url = 'https://api.aliyundrive.com/v2/batch'
        json = {"requests": [{"body": {"drive_id": self.drive_id, "file_id": file_id,
                                       "to_parent_file_id": parent_file_id},
                              "headers": {"Content-Type": "application/json"},
                              "id": file_id, "method": "POST", "url": "/file/move"}],
                "resource": "file"}
        logger.info(f'Move files {file_id} to {parent_file_id}')
        r = self._req.post(url, json=json)

        logger.debug(r.status_code)
        if r.status_code == 200:
            if 'message' in r.json()['responses'][0]['body']:
                print(r.json()['responses'][0]['body']['message'])
                return False
            return r.json()['responses'][0]['id']
        return False

    def get_user_info(self) -> UserInfo:
        """
        获取用户信息
        :return:
        """
        url = 'https://api.aliyundrive.com/v2/user/get'
        logger.info('Get user information.')
        r = self._req.post(url, json={})
        user_info = r.json()
        id_ = user_info['user_id']
        nick_name = user_info['nick_name']
        ctime = user_info['created_at']
        phone = user_info['phone']
        drive_id = user_info['default_drive_id']
        user_info = UserInfo(id=id_, nick_name=nick_name, ctime=ctime, phone=phone, drive_id=drive_id)
        logger.debug(user_info)
        self._user_info = user_info
        GLOBAL_VAR.user_info = user_info
        return user_info

    def create_file(self, file_name: str, parent_file_id: str = 'root', file_type: bool = False,
                    json: dict = None, force: bool = False) -> requests.models.Response:
        """
        创建文件
        :param file_name:
        :param parent_file_id:
        :param file_type:
        :param json:
        :param force:
        :return:
        """
        j = {
            "name": file_name,
            "drive_id": self.drive_id,
            "parent_file_id": parent_file_id,
            "content_hash_name": "sha1",
        }
        if file_type:
            f_type = 'file'
            check_name_mode = 'auto_rename'
            if force:
                check_name_mode = 'refuse'
        else:
            f_type = 'folder'
            check_name_mode = 'refuse'
        j.update({"type": f_type, 'check_name_mode': check_name_mode})
        if json:
            j.update(json)
        # 申请创建文件
        url = 'https://api.aliyundrive.com/v2/file/create'
        logger.info(f'Create file {file_name} in file {parent_file_id}.')
        r = self._req.post(url, json=j)
        logger.debug(j)
        if force and 'exist' in r.json():
            self.delete_file(r.json()['file_id'])
            return self.create_file(file_name, parent_file_id, file_type, json)
        return r

    def upload_file(self, parent_file_id: str = 'root', path: str = None, upload_timeout: float = 10,
                    retry_num: int = 3, force: bool = False, chunk_size: int = None, c: bool = False):
        """
        上传文件
        :param parent_file_id: 上传目录的id
        :param path: 上传文件路径
        :param upload_timeout: 分块上传超时时间
        :param retry_num:
        :param force: 强制覆盖
        :param chunk_size: 分块大小
        :param c: 断点续传
        :return:
        """
        path = Path(path)
        file_size = path.stat().st_size
        file_name = path.name
        self._chunk_size = chunk_size or self._chunk_size
        # 获取sha1
        content_hash = get_sha1(path, self._chunk_size)
        # 分片列表
        part_info_list = []
        count = int(file_size / self._chunk_size) + 1
        for i in range(count):
            part_info_list.append({"part_number": i + 1})
        json = {"size": file_size, "part_info_list": part_info_list, "content_hash": content_hash}
        task_info = {'path': str(path.absolute()), 'upload_id': None, 'file_id': None, 'chunk_size': self._chunk_size,
                     'part_number': None}
        path_list = []
        # 已存在任务
        if content_hash in GLOBAL_VAR.tasks:
            # 是否是列表或可迭代对象
            if isinstance(GLOBAL_VAR.tasks[content_hash].path, Iterable) and not isinstance(
                    GLOBAL_VAR.tasks[content_hash].path, str):
                path_list.extend(GLOBAL_VAR.tasks[content_hash].path)

            else:
                path_list.append(GLOBAL_VAR.tasks[content_hash].path)
            path_list = [str(Path(path_).absolute()) for path_ in path_list]
            path_list = list(set(path_list))
            flag = False
            # 是否存在上传时间
            if GLOBAL_VAR.tasks[content_hash].upload_time:
                for path_ in path_list:
                    # 是否存在路径
                    if path.absolute() == Path(path_).absolute():
                        flag = True
                        break
            # 已上传成功
            if flag:
                self._print.upload_info(path, status=True, existed=True)
                path_list.append(str(path.absolute()))
                path_list = list(set(path_list))
                GLOBAL_VAR.tasks[content_hash].path = path_list[0] if len(path_list) == 1 else path_list
                GLOBAL_VAR.file_hash_list.add(content_hash)
                return GLOBAL_VAR.tasks[content_hash].file_id
        is_rapid_upload = False
        # 断点续传且已存在任务
        if c and content_hash in GLOBAL_VAR.tasks:
            upload_id = GLOBAL_VAR.tasks[content_hash].upload_id
            file_id = GLOBAL_VAR.tasks[content_hash].file_id
            self._chunk_size = GLOBAL_VAR.tasks[content_hash].chunk_size
            part_number = GLOBAL_VAR.tasks[content_hash].part_number
            part_info_list = None
            # 是否是快速上传
            if upload_id:
                # 获取上传链接列表
                part_info_list = self.get_upload_url(path, upload_id, file_id, self._chunk_size, part_number)
            else:
                is_rapid_upload = True
            if not part_info_list and not is_rapid_upload:
                # 重新上传
                if str(path.absolute()) in path_list:
                    del path_list[str(path.absolute())]
                GLOBAL_VAR.tasks[content_hash].path = path_list[0] if len(path_list) == 1 else path_list
                return self.upload_file(parent_file_id=parent_file_id, path=path, upload_timeout=upload_timeout,
                                        retry_num=retry_num, force=force, chunk_size=chunk_size, c=c)
            elif part_info_list == 'AlreadyExist.File':
                # 已存在
                self._print.upload_info(path, status=True, existed=True)
                path_list.append(str(path.absolute()))
                path_list = list(set(path_list))
                GLOBAL_VAR.tasks[content_hash].path = path_list[0] if len(path_list) == 1 else path_list
                GLOBAL_VAR.file_hash_list.add(content_hash)
                return GLOBAL_VAR.tasks[content_hash].file_id
        if not (c and content_hash in GLOBAL_VAR.tasks) or is_rapid_upload:
            # 申请创建文件
            r = self.create_file(file_name=file_name, parent_file_id=parent_file_id, file_type=True, json=json,
                                 force=force)
            if 'rapid_upload' not in r.json():
                message = r.json()['message']
                logger.error(message)
                raise AliyunpanException(message)
            task_info = {'path': str(path.absolute()), 'upload_id': None,
                         'file_id': None, 'chunk_size': self._chunk_size,
                         'part_number': None}
            rapid_upload = r.json()['rapid_upload']
            if rapid_upload:
                self._print.upload_info(path, status=True, rapid_upload=True)
                file_id = r.json()['file_id']
                task_info['file_id'] = file_id
                task_info['upload_time'] = time.time()
                GLOBAL_VAR.tasks[content_hash] = task_info
                GLOBAL_VAR.file_hash_list.add(content_hash)
                if is_rapid_upload:
                    path_list.append(str(path.absolute()))
                    path_list = list(set(path_list))
                    GLOBAL_VAR.tasks[content_hash].path = path_list[0] if len(path_list) == 1 else path_list
                return file_id
            else:
                upload_id = r.json()['upload_id']
                file_id = r.json()['file_id']
                part_info_list = r.json()['part_info_list']
                task_info['upload_id'] = upload_id
                task_info['file_id'] = file_id
                task_info['part_number'] = 1
                GLOBAL_VAR.tasks[content_hash] = task_info
        self._print.upload_info(path)
        logger.debug(f'upload_id: {upload_id}, file_id: {file_id}, part_info_list: {part_info_list}')
        total_time = 0
        upload_bar = UploadBar(size=file_size)
        upload_bar.update(refresh_line=False)
        for i in part_info_list:
            part_number, upload_url = i['part_number'], i['upload_url']
            GLOBAL_VAR.tasks[content_hash].part_number = part_number
            with path.open('rb') as f:
                f.seek((part_number - 1) * self._chunk_size)
                chunk = f.read(self._chunk_size)
            if not chunk:
                break
            size = len(chunk)
            retry_count = 0
            start_time = time.time()
            while True:
                upload_bar.update(refresh_line=True)
                logger.debug(
                    f'(upload_id={upload_id}, file_id={file_id}, size={size}): Upload part of {part_number} to {upload_url}.')
                try:
                    # 开始上传
                    func_timeout.func_timeout(upload_timeout, lambda: self._req.put(upload_url, data=chunk))
                    break
                except func_timeout.exceptions.FunctionTimedOut:
                    logger.warn('Upload timeout.')
                    if retry_count is retry_num:
                        self._print.error_info(f'上传超时{retry_num}次，即将重新上传', refresh_line=True)
                        time.sleep(1)
                        return self.upload_file(parent_file_id, path, upload_timeout)
                    self._print.error_info('上传超时', refresh_line=True)
                    retry_count += 1
                    time.sleep(1)
                except KeyboardInterrupt:
                    raise
                except:
                    logger.error(sys.exc_info())
                    exc_type, exc_value, exc_traceback = sys.exc_info()
                    self._print.error_info(exc_type.__name__, refresh_line=True)
                    time.sleep(1)
                self._print.wait_info(refresh_line=True)
            end_time = time.time()
            t = end_time - start_time
            total_time += t
            k = part_number / part_info_list[-1]['part_number']
            upload_bar.update(ratio=k, refresh_line=True)
        # 上传完成保存文件
        url = 'https://api.aliyundrive.com/v2/file/complete'
        json = {
            "ignoreError": True,
            "drive_id": self.drive_id,
            "file_id": file_id,
            "upload_id": upload_id
        }
        r = self._req.post(url, json=json)
        if r.status_code == 200:
            total_time = int(total_time * 100) / 100
            self._print.upload_info(path, status=True, t=total_time, average_speed=file_size / total_time,
                                    refresh_line=True)
            GLOBAL_VAR.tasks[content_hash].upload_time = time.time()
            GLOBAL_VAR.file_hash_list.add(content_hash)
            return r.json()['file_id']
        else:
            self._print.upload_info(path, status=False, refresh_line=True)
            return False

    def get_upload_url(self, path: str, upload_id: str, file_id: str, chunk_size: int, part_number: int = 1) -> list:
        """
        获取上传地址
        :param path:
        :param upload_id:
        :param file_id:
        :param chunk_size:
        :param part_number:
        :return:
        """
        url = 'https://api.aliyundrive.com/v2/file/get_upload_url'
        path = Path(path)
        file_size = path.stat().st_size
        part_info_list = []
        count = int(file_size / chunk_size) + 1
        for i in range(count):
            part_info_list.append({"part_number": i + 1})
        json = {
            "drive_id": self.drive_id,
            "file_id": file_id,
            "part_info_list": part_info_list,
            "upload_id": upload_id,
        }
        r = self._req.post(url, json=json)
        if 'code' in r.json():
            return r.json()['code']
        return r.json()['part_info_list'][part_number - 1:]

    def get_access_token(self) -> str:
        """
        获取access_token
        :return:
        """
        # url = 'https://websv.aliyundrive.com/token/refresh'
        # json = {"refresh_token": self.refresh_token}
        url = 'https://auth.aliyundrive.com/v2/account/token'
        json = {"refresh_token": self.refresh_token, 'grant_type': 'refresh_token'}
        logger.info(f'Get ACCESS_TOKEN.')
        r = self._req.post(url, json=json, access_token=False)
        logger.debug(r.status_code)
        try:
            access_token = r.json()['access_token']
        except KeyError:
            raise InvalidRefreshToken
        GLOBAL_VAR.refresh_token = self.refresh_token
        GLOBAL_VAR.access_token = access_token
        logger.debug(access_token)
        return access_token

    def _access_token_gen(self) -> str:
        """
        access_token生成器
        :return:
        """
        access_token = None
        while True:
            if self._access_token:
                yield self._access_token
            elif access_token:
                yield access_token
            else:
                access_token = self.get_access_token()

    def get_drive_id(self) -> str:
        """
        获取drive_id
        :return:
        """
        drive_id = self.get_user_info().drive_id
        self._drive_id = drive_id
        GLOBAL_VAR.drive_id = drive_id
        return drive_id

    def _drive_id_gen(self) -> str:
        """
        drive_id生成器
        :return:
        """
        drive_id = None
        while True:
            if self._drive_id:
                yield self._drive_id
            elif drive_id:
                yield drive_id
            else:
                drive_id = self.get_drive_id()

    def get_download_url(self, file_id, expire_sec=14400) -> str:
        """
        获取分享链接
        :param file_id:
        :param expire_sec: 文件过期时间（秒）
        :return:
        """
        url = 'https://api.aliyundrive.com/v2/file/get_download_url'
        json = {'drive_id': self.drive_id, 'file_id': file_id, 'expire_sec': expire_sec}
        logger.info(f'Get file {file_id} download link, expiration time {expire_sec} seconds.')
        r = self._req.post(url, json=json)
        logger.debug(r.status_code)
        url = r.json()['url']
        logger.debug(f'file_id:{file_id},expire_sec:{expire_sec},url:{url}')
        return url

    def save_share_link(self, name: str, content_hash: str, content_hash_name: str, size: str,
                        parent_file_id: str = 'root', force: bool = False) -> bool:
        """
        保存分享文件
        :param content_hash_name:
        :param name:
        :param content_hash:
        :param size:
        :param parent_file_id:
        :param force:
        :return:
        """
        logger.info(f'name: {name}, content_hash:{content_hash}, size:{size}')
        json = {'content_hash': content_hash, 'size': int(size), 'content_hash_name': content_hash_name or 'sha1'}
        r = self.create_file(name, parent_file_id=parent_file_id, file_type=True, json=json, force=force)
        if r.status_code == 201 and 'rapid_upload' in r.json() and r.json()['rapid_upload']:
            return r.json()['file_id']
        elif 'message' in r.json():
            logger.debug(r.json())
            print(r.json()["message"])
        return False

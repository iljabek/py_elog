import http.client
import urllib.parse
import ssl
import os
import builtins

class Logbook(object):
    '''
    Logbook provides methods to interface with logbook on location: "server:port/subdir/logbook". User can create,
    edit, delete logbook messages.
    '''
    def __init__(self, hostname, logbook, port=None, user=None, password=None, subdir='', use_ssl=True,
                 encrypt_pwd=True):
        '''
        :param hostname: elog server hostname
        :param logbook: name of the logbook on the elog server
        :param port: elog server port (if not specified will default to '80' if use_ssl=False or '443' if use_ssl=True
        :param user: username (if authentication needed)
        :param password: password (if authentication needed) Password will be encrypted with sha256 unless
                         encrypt_pwd=False (default: True)
        :param subdir: subdirectory of logbooks locations
        :param use_ssl: connect using ssl?
        :param encrypt_pwd: To avoid exposing password in the code, this flag can be set to False and password
                            will then be handled as it is (user needs to provide sha256 encrypted password with
                            salt= '' and rounds=5000)
        :return:
        '''
        self.logbook = logbook

        self._user = user
        self._password= self.__handle_pswd(password, encrypt_pwd)

        self._logbook_path = urllib.parse.quote('/' + subdir + '/' + logbook + '/').replace('//', '/')

        if port:
            url = hostname + ':' + str(port)
        else:
            url = hostname

        if use_ssl:
            self.server = http.client.HTTPSConnection(hostname, port=port, context=ssl.SSLContext(ssl.PROTOCOL_TLSv1))
            self._url =  'https://' + url + self._logbook_path
        else:
            self.server = http.client.HTTPConnection(hostname, port=port)
            self._url =  'http://' + url + self._logbook_path

    def post_msg(self, message, msg_id=None, reply=False, attributes=None, attachments=None, encoding='plain',
                 **kwargs):
        '''
        Posts message to the logbook. If msg_id is not specified new message will be created, otherwise existing
        message will be edited, or a reply (if reply=True) to it will be created. This method returns the msg_id
        of the newly created message.

        :param message: string with message text
        :msg_id: ID number of message to edit or reply. If not specified new message is created.
        :reply: If 'True' reply to existing message is created instead of editing it
        :param attributes: Dictionary of attributes. Following attributes are used internally by the elog and will be
                           ignored: Text, Date, Encoding, Reply to, In reply to, Locked by, Attachment
        :param attachments: list of:
                                  - file like objects which read() will return bytes (if file_like_object.name is not
                                    defined, default name "attachmet<i>" will be used.
                                  - paths to the files
                            All items will be appended as attachment to the elog entry. In case of unknown
                            attachment an exception LogbookInvalidAttachment will be raised.
        :param encoding: can be: 'plain' -> plain text, 'html'->html-text, 'ELCode' --> elog formatting syntax
        :param kwargs: Anything in the kwargs will be interpreted as attribute. e.g.: logbook.post_msg('Test text',
                       Author='Rok Vintar), "Author" will be sent as an attribute. If named same as one of the
                       attributes defined in "attributes", kwargs will have priority.

        :return: msg_id
        '''

        attributes = attributes or {}
        attributes = {**attributes, **kwargs} # kwargs as attributes with higher priority

        attachments = attachments or []

        if msg_id and reply: # Reply to
            attributes['reply_to'] = str(msg_id)

        elif msg_id: # Edit existing
            attributes['edit_id'] = str(msg_id)
            attributes['skiplock'] = '1'

            # Handle existing attachments
            msg_to_edit, attrib_to_edit, attach_to_edit = self.read_msg(msg_id)
            i = 0
            for attachment in attach_to_edit:
                if attachment:
                    # Existing attachments must be passed as regular arguments attachment<i> with walue= file name
                    # Read message returnes full urls to existing attachments:
                    # <hostename>:[<port>][/<subdir]/<logbook>/<msg_id>/<file_name>
                    attributes['attachment' + str(i)] = os.path.basename(attachment)
                    i += 1

            for attribute, data in attributes.items():
                new_data = attributes.get(attribute)
                if not new_data is None:
                    attrib_to_edit[attribute] = new_data

        content, headers, boundary = self.__compose_msg(message, attributes, attachments)
        response = self.__send_msg(content, headers)

        for header in response.getheaders():
            if header[0] == 'Location':
                # Successfully posted. Get and return msg_id from response
                return(int(header[1].split('/')[-1]))
            #else:
                # else Todo raise custom exception

    def read_msg(self, msg_id):
        '''
        Reads message from the logbook server and returns tuple of (message, attributes, attachments) where:
        message: string with message body
        attributes: dictionary of all attributes returned by the logbook
        attachments: list of urls to attachments on the logbook server

        :param msg_id: ID of the message to be read
        :return: message, attributes, attachments
        '''
        # First build request, then parse response
        request_msg = self._logbook_path +str(msg_id) + '?cmd=download'

        request_headers =  self.__make_base_headers()

        if self._user or self._password:
            request_headers['Cookie'] = self.__make_user_and_pswd_cookie()


        self.server.request('GET', request_msg, headers=request_headers)
        response = self.server.getresponse()
        # TODO error handling


        # Parse message to separate message body, attributes and attachments
        attributes = dict()
        attachments = list()

        returned_msg = response.read().decode('utf-8').splitlines()
        delimeter_idx = returned_msg.index('========================================')

        message = '\n'.join(returned_msg[delimeter_idx+1:])
        for line in returned_msg[0:delimeter_idx]:
            line = line.split(': ')
            data = ''.join(line[1:])
            if line[0] == 'Attachment':
                attachments = data.split(',')
                # Here are only attachment names, make a full url out of it, so they could be
                # recognisable by others, and downloaded if needed
                attachments = [self._url+ '{0}'.format(i) for i in attachments]
            else:
                attributes[line[0]] = data

        return(message, attributes, attachments)

    def delete_msg(self, msg_id):
        '''
        Deletes message from logbook. It also deletes all of its attachments from the server.

        :param msg_id: message to be deleted
        :return:
        '''
        request_msg = self._logbook_path +str(msg_id) + '?cmd=Delete&confirm=Yes'
        request_headers =  self.__make_base_headers()

        if self._user or self._password:
            request_headers['Cookie'] = self.__make_user_and_pswd_cookie()


        self.server.request('GET', request_msg, headers=request_headers)
        response = self.server.getresponse()
        # TODO error handling



    def __compose_msg(self, message, attributes, attachments):
        '''
        Prepares all message components to be sent with http.
        :param message: message body
        :param attributes: message attributes
        :param attachments: message attachments
        :return: content, headers, boudnary
        '''
        boundary = b'---------------------------1F9F2F8F3F7F' #TODO randomise boundary
        headers = self.__make_base_headers()
        content = self.__make_base_msg_content(boundary)

        # Clear attributes that are reserved by elog and must not be sent to the server
        self.__remove_reserved_attributes(attributes)

        # Add main message, then append attributes and add attachments
        content += self.__param_to_content ('Text', message, boundary)
        if attributes:
            for name, data in attributes.items():
                content += self.__param_to_content (name, data, boundary)

        if attachments:
            content += self.__attachments_to_content(attachments, boundary)

        content += boundary
        # from __make_base_header set Content-Type: multipart/form-data
        headers['Content-Type'] += '; boundary=' + boundary.decode('utf-8')
        return(content, headers, boundary)

    def __send_msg(self, content, headers):
        '''
        Sends HTTP content and headers (prepared with __compose_msg) to the logbook server and returns response
        :param content: http content
        :param headers: http headers
        :return: response from the server
        '''
        self.server.request('POST', self._logbook_path , content, headers=headers)
        response = self.server.getresponse()

        return(response)

    def __make_base_headers(self):
        '''
        Creates base headers, which should be used by all messages.
        :return: dictionary of headers
        '''
        header = dict()
        header['User-Agent'] = 'ELOG'
        header['Content-Type'] = 'multipart/form-data'

        return(header)

    def __make_base_msg_content(self, boundary):
        '''
        Create base message content which is used by all messages.
        :param boundary: decimeter between Content-Disposition
        :return: content string
        '''
        content = self.__param_to_content('cmd', 'Submit', boundary)
        content += self.__param_to_content('exp', self.logbook, boundary)
        if self._user:
            content += self.__param_to_content('unm', self._user, boundary)
        if self._password:
            content += self.__param_to_content('upwd', self._password, boundary)

        return(content)

    def __param_to_content (self, name, data, boundary, **kwargs):
        '''
        Parses parameter name and data to content format:
            Content-Disposition: form-data; name='name'; kwarg0 = 'kwargs[0]'; ....

            data

        :param name: name of the content (usually attribute name in case of elog)
        :param data: value of the attribute (or file content for example)
        :param boundary: decimeter between Content-Disposition
        :param kwargs: optional parameters after name=''
        :return: content string
        '''
        content =b''
        newline= b'\r\n'

        if isinstance(name, str):
            name = name.encode('utf-8')

        if isinstance(data, str):
            data = data.encode('utf-8')

        content += boundary + newline +  b'Content-Disposition: form-data; name=\"' + name + b'\"'

        if kwargs:
            for key_, value_ in kwargs.items():
                content += b'; ' + key_.encode('utf-8') + b'=\"' + value_.encode('utf-8') + b'\"'

        if isinstance(data, str):
            data = data.encode('utf-8')

        content += newline + newline + data + b'\r\n' + newline

        return(content)

    def __attachments_to_content(self, files, boundary):
        '''
        Parses attachments to content objects. Attachments can be:
            - file like objects: must have method read() which returns bytes. If it has attribute .name it will be used
              for attachment name, otherwise generic attribute<i> name will be used.
            - path to the file on disk

        Note that if attachment is is an url pointing to the existing Logbook server it will be ignored and no
        exceptions will be raised. This can happen if attachments returned with read_method are resend.

        :param files: list of file like objects or paths
        :param boundary: decimeter between Content-Disposition
        :return: content string
        '''
        content = b''
        i = 0
        for file_obj in files:
            if hasattr(file_obj, 'read'):
                i += 1
                attribute_name = 'attfile' + str(i)

                filename = attribute_name  # If file like object has no name specified use this one
                candidate_filename = os.path.basename(file_obj.name)

                if filename: # use only if not empty string
                    filename = candidate_filename

                content += self.__param_to_content(attribute_name, file_obj.read(), boundary, filename=filename)

            elif isinstance(file_obj, str):
                # Check if it is:
                #           - a path to the file --> open file and append
                #           - an url pointing to the existing Logbook server --> ignore

                if os.path.isfile(file_obj):
                    i += 1
                    attribute_name = 'attfile' + str(i)

                    file_obj = builtins.open(file_obj, 'rb')
                    print(file_obj)
                    content += self.__param_to_content(attribute_name, file_obj.read(), boundary,
                                                       filename=file_obj.name)

                elif not file_obj.startswith(self._url):
                    raise TypeError('Invalid type of attachment: \"' + file_obj + '\".')
            else:
                raise TypeError('Invalid type of attachment[' + str(i) + '].')
        # Todo type errors replace
        return(content)

    def __remove_reserved_attributes(self, attributes):
        '''
        Removes elog reserved attributes (from the attributes dict) that can not be sent.

        :param attributes: dictionary of attributes to be cleaned.
        :return:
        '''

        if attributes:
            attributes.get('$@MID@$', None)
            attributes.pop('Date', None)
            attributes.pop('Attachment', None)
            attributes.pop('Text', None)
            attributes.pop('Encoding', None)
            attributes.pop('Locked by', None)
            attributes.pop('In reply to', None)
            attributes.pop('Reply to', None)

    def __make_user_and_pswd_cookie(self):
        '''
        prepares user name and password cookie. It is sent in header when posting a message.
        :return: user name and password value for the Cookie header
        '''
        cookie=''
        if self._user:
            cookie += 'unm=' + self._user + ';'
        if self._password:
            cookie += 'upwd=' + self._password + ';'

        return(cookie)

    def __handle_pswd(self, password, encrypt=True):
        '''
        Takes password string and returns password as needed by elog. If encrypt=True then password will be
        sha256 encrypted (salt='', rounds=5000). Before returning password, any trailing $5$$ will be removed
        independent off encrypt flag.

        :param password: password string
        :param encrypt: encrypt password?
        :return: elog prepared password
        '''
        if encrypt and password:
            from passlib.hash import sha256_crypt
            return(sha256_crypt.encrypt(password, salt='', rounds=5000)[4:])
        elif password and password.startswith('$5$$'):
            return(password[4:])
        else:
            return(password)

def open(*args, **kwargs):
    '''
    Will return a Logbook object. All arguments are passed to the logbook constructor.
    :param args:
    :param kwargs:
    :return: Logbook() instance
    '''
    return(Logbook(*args, **kwargs))
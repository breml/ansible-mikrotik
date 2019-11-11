#!/usr/bin/env python
# coding: utf-8
"""MikroTik RouterOS CLI ansible module"""

import os
import sys
import socket

try:
    HAS_SSHCLIENT = True
    import paramiko
except ImportError as import_error:
    HAS_SSHCLIENT = False
try:
    SHELLMODE = False
    from ansible.module_utils.basic import AnsibleModule
except ImportError:
    SHELLMODE = True
else:
    if sys.stdin.isatty():
        SHELLMODE = True

SHELLDEFS = {
    'username': 'admin',
    'password': '',
    'key_filename': None,
    'timeout': 30,
    'port': 22,
    'test_change': True,
    'command': None,
    'upload_script': None,
    'upload_file': None
}
MIKROTIK_MODULE = '[github.com/nekitamo/ansible-mikrotik] v17.07'
DOCUMENTATION = """
---
module: mikrotik_command
short_description: Execute single or multiple MikroTik RouterOS CLI commands
description:
    - Execute one or more MikroTik RouterOS CLI commands via ansible or shell
    - Execute multiple commands from a file or save them as a RouterOS script
    - Authenticate via username/password or by using ssh keys
return_data:
    - changed
    - stdout
    - stdout_lines
options:
    command:
        description:
            - MikroTik command to execute on the device
        required: false
        default: null
    hostname:
        description:
            - IP Address or hostname of the MikroTik device
        required: true
        default: null
    upload_script:
        description:
            - Upload commands from specified file, save as a script and execute the script
        required: no
        default: false
    test_change:
        description:
            - Test for configuration changes after command execution (slow)
        required: no
        default: false
    upload_file:
        description:
            - Upload specified file before command/script execution
        required: no
        default: null
    port:
        description:
            - SSH listening port of the MikroTik device
        required: no
        default: 22
    username:
        description:
            - Username used to login for the device
        required: no
        default: ansible
    password:
        description:
            - Password used to login to the device
        required: no
        default: null
"""
EXAMPLES = """
  - name: Upload and assign ssh key
    mikrotik_command:
      hostname: "{{ inventory_hostname }}"
      username: ansible
      password: ""
      upload_file: "~/.ssh/id_rsa.pub"
      command: "/user ssh-keys import public-key-file=id_rsa.pub user=ansible"
  - name: Reboot router
    mikrotik_command:
      hostname: "{{ inventory_hostname }}"
      command: "system reboot"
"""
RETURN = """
stdout:
    description: Returns router response in a single string
    returned: always
    type: string
stdout_lines:
    description: Returns router response as a list of strings
    returned: always
    type: list
"""
SHELL_USAGE = """
mikrotik_command.py --hostname=<hostname> (--command=<command> | --upload_script=<file>)
    [--upload_file=<file>] [--port=<port>] [--username=<username>] [--password=<password>] [--test_change]
"""

def safe_fail(module, device=None, **kwargs):
    """closes device before module fail"""
    if device:
        device.close()
    module.fail_json(**kwargs)

def safe_exit(module, device=None, **kwargs):
    """closes device before module exit"""
    if device:
        device.close()
    module.exit_json(**kwargs)

def parse_opts(cmdline):
    """returns SHELLMODE command line options as dict"""
    options = SHELLDEFS
    for opt in cmdline:
        if opt.startswith('--'):
            try:
                arg, val = opt.split("=", 1)
            except ValueError:
                arg = opt
                val = True
            else:
                if val.lower() in ('no', 'false', '0'):
                    val = False
                elif val.lower() in ('yes', 'true', '1'):
                    val = True
            arg = arg[2:]
            if arg in options or arg == 'hostname':
                options[arg] = val
            else:
                print SHELL_USAGE
                sys.exit("Unknown option: --%s" % arg)
    if 'hostname' not in options:
        print SHELL_USAGE
        sys.exit("Hostname is required, specify with --hostname=<hostname>")
    return options

def device_connect(module, device, rosdev):
    """open ssh connection with or without ssh keys"""
    if SHELLMODE:
        sys.stdout.write("Opening SSH connection to %s(%s:%s)... "
                         % (rosdev['hostname'], rosdev['ipaddress'], rosdev['port']))
        sys.stdout.flush()
    try:
        device.connect(rosdev['ipaddress'], username=rosdev['username'],
                       password=rosdev['password'], port=rosdev['port'],
                       timeout=rosdev['timeout'])
    except Exception:
        try:
            device.connect(rosdev['ipaddress'], username=rosdev['username'],
                           password=rosdev['password'], port=rosdev['port'],
                           timeout=rosdev['timeout'], allow_agent=False,
                           look_for_keys=False)
        except Exception as ssh_error:
            if SHELLMODE:
                sys.exit("failed!\nSSH error: " + str(ssh_error))
            safe_fail(module, device, msg=str(ssh_error),
                      description='error opening ssh connection to %s(%s:%s)' %
                      (rosdev['hostname'], rosdev['ipaddress'], rosdev['port']))
    if SHELLMODE:
        print "succes."

def sshcmd(module, device, timeout, command):
    """executes a command on the device, returns string"""
    try:
        _stdin, stdout, _stderr = device.exec_command(command, timeout=timeout)
    except Exception as ssh_error:
        if SHELLMODE:
            sys.exit("SSH command error: " + str(ssh_error))
        safe_fail(module, device, msg=str(ssh_error),
                  description='SSH error while executing command')
    response = stdout.read()
    if 'bad command name ' not in response:
        if 'syntax error ' not in response:
            if 'failure: ' not in response:
                return response.rstrip()
    if SHELLMODE:
        print "Command: " + str(command)
        sys.exit("Error: " + str(response))
    safe_fail(module, device, msg='bad command name or syntax error',
              description='bad command name or syntax error')

def main():
    """RouterOS command line interface main"""
    rosdev = {}
    cmd_timeout = 30
    changed = True
    if not SHELLMODE:
        module = AnsibleModule(
            argument_spec=dict(
                command=dict(default=None, type='str'),
                upload_script=dict(default=None, type='path'),
                test_change=dict(default=True, type='bool'),
                upload_file=dict(default=None, type='path'),
                key_filename=dict(default=None, type='path'),
                port=dict(default=22, type='int'),
                timeout=dict(default=30, type='float'),
                hostname=dict(required=True, type='str'),
                username=dict(default='ansible', type='str'),
                password=dict(default=None, type='str', no_log=True),
            ), supports_check_mode=False
        )
        if not HAS_SSHCLIENT:
            safe_fail(module, msg='There was a problem loading module: ',
                      error=str(import_error))
        if not module.params['command'] and not module.params['upload_script']:
            safe_fail(module, msg='command required',
                  description='command or upload_script is required')
        command = module.params['command']
        upload_script = module.params['upload_script']
        test_change = module.params['test_change']
        upload_file = module.params['upload_file']
        rosdev['key_filename'] = module.params['key_filename']
        rosdev['hostname'] = module.params['hostname']
        rosdev['username'] = module.params['username']
        rosdev['password'] = module.params['password']
        rosdev['port'] = module.params['port']
        rosdev['timeout'] = module.params['timeout']

    else:
        if not HAS_SSHCLIENT:
            sys.exit("SSH client error: " + str(import_error))
        if not SHELLOPTS['command'] and not SHELLOPTS['upload_script']:
            print SHELL_USAGE
            sys.exit("command required, specify with --command=<cmd> or --upload_script=<file>")
        rosdev['hostname'] = SHELLOPTS['hostname']
        rosdev['username'] = SHELLOPTS['username']
        rosdev['password'] = SHELLOPTS['password']
        rosdev['port'] = SHELLOPTS['port']
        rosdev['timeout'] = SHELLOPTS['timeout']
        rosdev['key_filename'] = SHELLOPTS['key_filename']
        command = SHELLOPTS['command']
        upload_script = SHELLOPTS['upload_script']
        test_change = SHELLOPTS['test_change']
        upload_file = SHELLOPTS['upload_file']
        module = None

    try:
        rosdev['ipaddress'] = socket.gethostbyname(rosdev['hostname'])
    except socket.gaierror as dns_error:
        if SHELLMODE:
            sys.exit("Hostname error: " + str(dns_error))
        safe_fail(module, msg=str(dns_error),
                  description='error getting device address from hostname')

    device = paramiko.SSHClient()
    device.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    device_connect(module, device, rosdev)

    if test_change:
        before = sshcmd(module, device, cmd_timeout, "export")

    if upload_file and os.path.isfile(upload_file):
        uploaded = os.path.basename(upload_file)
        sftp = device.open_sftp()
        sftp.put(upload_file, uploaded)
        sftp.close()
        response = sshcmd(module, device, cmd_timeout,
                          'file print terse without-paging where name="'
                          + uploaded + '"')
        if uploaded not in response:
            if SHELLMODE:
                device.close()
                sys.exit("Error uploading file: " + uploaded)
            safe_fail(module, device, msg="upload failed!",
                      description='error uploading file: ' + uploaded)

    if upload_script and os.path.isfile(upload_script):
        response = ''
        try:
            with open(upload_script) as scriptfile:
                script = scriptfile.readlines()
                scriptfile.close()
        except Exception as cmd_error:
            if SHELLMODE:
                device.close()
                sys.exit("Script file error: " + str(cmd_error))
            safe_fail(module, device, msg=str(cmd_error),
                      description='error opening script file')
        scriptname = os.path.basename(upload_script)
        response += sshcmd(module, device, cmd_timeout,
                           '/system script remove [ find name="'
                           + scriptname + '" ]')
        cmd = '/system script add name="' + scriptname + '" source="'
        for line in script:
            line = line.rstrip()
            line = line.replace("\\", "\\\\")
            line = line.replace("\"", "\\\"")
            line = line.replace("$", "\\$")
            cmd += line + "\\r\\n"
        response += sshcmd(module, device, cmd_timeout, cmd + '"')
        response += sshcmd(module, device, cmd_timeout,
                           '/system script run [ find name="'
                           + scriptname + '" ]')
    else:
        if upload_file and command == 'user ssh-keys import':
            response = sshcmd(module, device, cmd_timeout,
                              '/user ssh-keys import public-key-file="' +
                              uploaded + '" user=' + rosdev['username'])
        else:
            response = sshcmd(module, device, cmd_timeout, command)
    if response:
        response += '\r\n'

    if test_change:
        after = sshcmd(module, device, cmd_timeout, "/export")
        before = before.splitlines(1)[1:]
        after = after.splitlines(1)[1:]
        if len(before) == len(after):
            for bef, aft in zip(before, after):
                if aft != bef:
                    break
            else:
                changed = False

    if SHELLMODE:
        device.close()
        print str(response)
        sys.exit(0)

    stdout_lines = []
    for line in response.splitlines():
        if line:
            stdout_lines.append(line.strip())

    safe_exit(module, device, stdout=response, stdout_lines=stdout_lines,
              changed=changed)

if __name__ == '__main__':
    if len(sys.argv) > 1 or SHELLMODE:
        print "Ansible MikroTik Library %s" % MIKROTIK_MODULE
        SHELLOPTS = parse_opts(sys.argv)
        SHELLMODE = True
    main()

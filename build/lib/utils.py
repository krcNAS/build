#+
# Copyright 2015 iXsystems, Inc.
# All rights reserved
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted providing that the following conditions
# are met:
# 1. Redistributions of source code must retain the above copyright
#    notice, this list of conditions and the following disclaimer.
# 2. Redistributions in binary form must reproduce the above copyright
#    notice, this list of conditions and the following disclaimer in the
#    documentation and/or other materials provided with the distribution.
#
# THIS SOFTWARE IS PROVIDED BY THE AUTHOR ``AS IS'' AND ANY EXPRESS OR
# IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
# WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
# ARE DISCLAIMED.  IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR ANY
# DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
# DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS
# OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION)
# HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT,
# STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING
# IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.
#
#####################################################################

import os
import sys
import time
import datetime
import subprocess
import string
import signal
import inspect
from collections import defaultdict
from dsl import load_file


_abort_func = None


def interrupt(signal, frame):
    error('Build interrupted by SIGINT')


def sh(*args, **kwargs):
    logfile = kwargs.pop('log', None)
    mode = kwargs.pop('mode', 'w')
    nofail = kwargs.pop('nofail', False)
    cmd = e(' '.join(args), **get_caller_vars())
    if logfile:
        sh('mkdir -p', os.path.dirname(logfile))
        f = open(logfile, mode)

    debug('sh: {0}', cmd)
    ret = subprocess.call(cmd, stdout=f if logfile else None, stderr=subprocess.STDOUT, shell=True, bufsize=65536, close_fds=False)
    if ret != 0 and not nofail:
        info('Failed command: {0}', cmd)
        info('Returned value: {0}', ret)
        error('Build failed')

    return ret


def sh_spawn(*args, **kwargs):
    logfile = kwargs.pop('log', None)
    mode = kwargs.pop('mode', 'w')
    nofail = kwargs.pop('nofail', False)
    detach = kwargs.pop('detach', False)
    cmd = e(' '.join(args), **get_caller_vars())
    if logfile:
        sh('mkdir -p', os.path.dirname(logfile))
        f = open(logfile, mode)

    def preexec():
        os.setpgrp()

    debug('sh: {0}', cmd)
    return subprocess.Popen(cmd, stdout=f if logfile else None, preexec_fn=preexec if detach else None, stderr=subprocess.STDOUT, shell=True)


def sh_str(*args, **kwargs):
    logfile = kwargs.pop('log', None)
    mode = kwargs.pop('mode', 'w')
    cmd = e(' '.join(args), **get_caller_vars())
    if logfile:
        f = open(logfile, mode)

    try:
        return subprocess.check_output(cmd, shell=True, close_fds=False).decode('utf8').strip()
    except subprocess.CalledProcessError:
        return ''


def chroot(root, *args, **kwargs):
    root = e(root, **get_caller_vars())
    cmd = e(' '.join(args), **get_caller_vars())
    return sh("chroot ${root} /bin/sh -c '${cmd}'", **kwargs)


def setup_env():
    signal.signal(signal.SIGINT, interrupt)
    dsl = load_file('${BUILD_CONFIG}/env.pyd', os.environ)
    for k, v in dsl.items():
        if k.isupper():
            os.environ[k] = v


def env(name, default=None):
    return os.getenv(name, default)


def readfile(filename):
    filename = e(filename, **get_caller_vars())
    with open(filename, 'r', encoding='utf8', errors='ignore') as f:
        return f.read().strip()


def setfile(filename, contents):
    filename = e(filename, **get_caller_vars())
    debug('setfile: {0}', filename)

    if not os.path.isdir(os.path.dirname(filename)):
        sh('mkdir -p', os.path.dirname(filename))

    with open(filename, 'wb') as f:
        if isinstance(contents, str):
            contents = contents.encode('utf8')
        f.write(contents)
        f.write(b'\n')


def appendfile(filename, contents, nl=True):
    filename = e(filename, **get_caller_vars())
    contents = e(contents, **get_caller_vars())
    debug('appendfile: {0}', filename)

    if not os.path.isdir(os.path.dirname(filename)):
        sh('mkdir -p', os.path.dirname(filename))

    f = open(filename, 'a')
    f.write(contents)
    if nl:
        f.write('\n')


def abort():
    global _abort_func
    if _abort_func is not None:
        tmpfn = _abort_func
        _abort_func = None
        tmpfn()


def on_abort(func):
    global _abort_func

    def fn(signum, frame):
        info('ERROR: Build aborted')
        abort()
        sys.exit(1)

    _abort_func = func
    signal.signal(signal.SIGINT, fn)
    signal.signal(signal.SIGTERM, fn)
    signal.signal(signal.SIGQUIT, fn)


def get_caller_vars():
    frame = inspect.currentframe()
    try:
        parent = frame.f_back.f_back
        kwargs = parent.f_locals
        kwargs.update(parent.f_globals)
    finally:
        del frame

    return kwargs


def e(s, **kwargs):
    s = os.path.expandvars(s)
    if not kwargs:
        kwargs = get_caller_vars()

    t = string.Template(s)
    d = defaultdict(lambda: '')
    d.update(kwargs)
    return t.safe_substitute(d)


def pathjoin(*args):
    return os.path.join(*[e(i) for i in args])


def objdir(path):
    return os.path.join(e('${OBJDIR}'), e(path, **get_caller_vars()))


def template(filename, variables=None):
    f = open(e(filename), 'r')
    t = string.Template(f.read())
    variables = variables or {}
    variables.update(os.environ)
    result = t.safe_substitute(**variables)
    f.close()
    return result


def glob(path):
    import glob as g
    return g.glob(e(path, **get_caller_vars()))


def walk(path):
    path = e(path, **get_caller_vars())
    for root, dirs, files in os.walk(path):
        for name in files:
            yield os.path.relpath(os.path.join(root, name), path)

        for name in dirs:
            yield os.path.relpath(os.path.join(root, name), path)


def sha256(filename, output=None):
    filename = e(filename, **get_caller_vars())
    if not output:
        output = filename + '.sha256'
    else:
        output = e(output, **get_caller_vars())

    setfile(output, sh_str("sha256 ${filename}"))


def import_function(filename, fname):
    module = __import__(filename)
    return getattr(module, fname)


def elapsed():
    timestamp = env('BUILD_STARTED', str(int(time.time())))
    td = int(timestamp)
    return str(datetime.timedelta(seconds=time.time() - td)).split('.')[0] # XXX


def info(fmt, *args):
    print('[{0}] ==> '.format(elapsed()) + e(fmt.format(*args)))


def debug(fmt, *args):
    if env('BUILD_LOGLEVEL') == 'DEBUG':
        log(fmt, *args)


def log(fmt, *args):
    print(e(fmt.format(*args)))


def error(fmt, *args):
    print('[{0}] ==> ERROR: '.format(elapsed()) + e(fmt.format(*args)))
    abort()
    sys.exit(1)


def get_port_names(ports):
    for i in ports:
        if isinstance(i, dict):
            yield i.name
            continue

        yield i


def is_elf(filename):
    if os.path.islink(filename):
        return False

    if not os.path.isfile(filename):
        return False

    with open(filename, 'rb') as f:
        header = f.read(4)
        return header == b'\x7fELF'

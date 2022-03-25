#!/usr/bin/env python3
#============================================================================
# Create a MozillaBuild installer
#============================================================================
# This packaging script is intended to be entirely self-contained.
#
# However, it's within the realm of possibility of making changes to the host
# machine it's running on, so it's recommmended to be run within a VM instead.
#
# System Requirements:
#   * 64-bit Windows 7+
#   * MS Visual Studio 2017+
#   * Windows 10 SDK (should be included with Visual Studio installer)
#   * Existing MYSYS2 installation (ex in: "C:\msys64")
#
# Usage Instructions:
#   The script has built-in defaults that should allow for the package to be
#   built simply by invoking ./packageit.py from a MozillaBuild terminal.
#   It also supports command line arguments for changing the default paths
#   if desired.
#============================================================================

import os
import re
import json
from sys import stdout
from shutil import copyfile, copytree
from os.path import join as path, basename, dirname
from zipfile import ZipFile
from tarfile import TarFile
from argparse import ArgumentParser
from functools import reduce
from subprocess import check_call, run, CalledProcessError, PIPE

#============================================================================
# USAGE

argparser = ArgumentParser()

argparser.add_argument(
    '-m', '--msys2-ref-path', type=path,
    help='Path to reference MSYS2 installation (containing curl and pacman)',
)
argparser.add_argument(
    '-s', '--sources-path', type=path,
    help='Path to source directory for bundled tools and configs',
)
argparser.add_argument(
    '-o', '--staging-path', type=path,
    help='Path to desired staging directory'
)
argparser.add_argument(
    '-v', '--msvc-path', type=path,
    help='Path to Visual Studio installation',
)
argparser.add_argument(
    '-w', '--win10-sdk-path', type=path,
    help='Path to Windows 10 SDK installation folder'
)
argparser.add_argument(
    '--fetch-sources', action='store_true',
    help='Download MSYS2 packags sources to "'+path('STAGING-PATH', 'src')+'"',
)
argparser.add_argument(
    '--fetch-utils', nargs='?', choices=['cache', 'dont-cache'],
    help='Download latest tool updates to "'+path('.', 'temp')+'", and bundle them.',
)
argparser.add_argument(
    '--msys-extra', action='store_true',
    help='Bundle pacman, pkg-config, info-zip, emacs and UPX (with ucl) from the MSYS2 base repo',
)
argparser.add_argument(
    '--msys-devel', action='store_true',
    help='Bundle libicu4c-devel, libffi-devel, libevent-devel and zlib-devel from MSYS2',
)
argparser.add_argument(
    '--nsis-only', action='store_true',
    help='skips staging/build, and uses artifacts from a previous run, just to rebuild the installer',
)

#============================================================================
# OUTPUT

#----------------------------------------------------------------------------
# ANSI SGR codes

# SGR BASE STYLE enable
NORMAL=0; BOLD=1; DIM=2; ITALIC=3; UNDERLINE=4
ONOFF=5; BLINK=6; INV=7; HIDDEN=8; STRIKEOUT=9
# add to SGR BASE STYLE to disable (except for NORMAL)
NOT= +20

# SGR BASE COLOR (text)
DARK=30; RED    =31; GREEN=32; YELLOW=33
BLUE=34; MAGENTA=35; CYAN =36; WHITE =37
# add to SGR BASE COLOR to set BkGR / BRIght color
BGR= +10; BRI= +60

#----------------------------------------------------------------------------

# SGR helper
def C(sgr='', *sgrs):
    return '\033[0;{}m'.format(';'.join(map(str, [sgr, *sgrs])))

# raw stdout flushed
def stdout(string):
    from sys import stdout as out;
    out.write(string); out.flush()

# print to str
def sprint(*args, sep=' ', end=''): return sep.join(map(str, args)) + end

# print ANSI to win console
def printl(*args, sep=' ', end=f'{C()}\n'):
    os.system('color') # magic hack
    stdout(sprint(*args, sep=sep, end=end))

# print an error optionally with code
def error(message, code=None):
    printl(f'{C(DIM, RED, YELLOW+BGR, INV)} ! {code or ""} {C()} {message}')

# perl-like chomp: eats last newline\carriage feed pair
def chomp(buf):
    if not buf: return buf
    if buf.endswith('\n\r') or buf.endswith('\r\n'): return buf[:-2]
    if buf.endswith('\n')   or buf.endswith('\r')  : return buf[:-1]
    return buf

#============================================================================
# utilities for setting default arg values

PWD     = dirname(os.path.abspath(__file__))
VSWHERE = path(PWD, 'sources', 'vswhere.exe')

# capture command output
# print (uncaptured) error message + throw on failure
def output(cmd, *args, **kwargs):
    try: return chomp(run(cmd, *args, check=True, text=True, encoding='UTF-8', stdout=PIPE, stderr=PIPE, **kwargs).stdout)
    except CalledProcessError as ex: error(ex.output, ex.returncode); raise ex

# query a property of latest msvc/prerelease/buildtools installed
def vswhere(property):
    return output([VSWHERE, '-products', '*', '-latest', '-prerelease', '-format', 'value', '-utf8', '-property', property])

# detect winsdk path
def sdkpath():
    from winreg import OpenKey, HKEY_LOCAL_MACHINE as HKLM, QueryValueEx
    regkey = OpenKey(HKLM, path('SOFTWARE', 'WOW6432Node', 'Microsoft', 'Microsoft SDKs\Windows', 'v10.0'))
    sdkdir, _t = QueryValueEx(regkey, 'InstallationFolder')
    sdkver, _t = QueryValueEx(regkey, 'ProductVersion')
    return path(sdkdir, 'bin', f'{sdkver}.0', 'x64')

#============================================================================
# PARSE ARGS

argparser.set_defaults(
    source_path    = path(PWD, 'sources'),
    msys2_ref_path = path('C:\\msys64'),
    staging_path   = path(PWD, 'stage'),
    msvc_path      = vswhere('installationPath'),
    win10_sdk_path = sdkpath(),
    fetch_sources  = False,
    fetch_utils    = True,
    msys_extra     = True,
    msys_devel     = False,
    nsis_only      = False,
)

args = argparser.parse_args()

SRC_PATH   = args.source_path
REF_PATH   = args.msys2_ref_path
OUT_PATH   = args.staging_path
MSVC_PATH  = args.msvc_path
WSDK_PATH  = args.win10_sdk_path
FETCH_SRCS = args.fetch_sources
FETCH_UTIL = args.fetch_utils
MSYS_EXTRA = args.msys_extra
MSYS_DEVEL = args.msys_devel
NSIS_ONLY  = args.nsis_only

#============================================================================
# SUPPLEMENTARY CONFIG

# requred binaries from mreferenced MSYS
REF_PACMAN = path(REF_PATH, 'usr', 'bin', 'pacman.exe')
REF_CURL   = path(REF_PATH, 'usr', 'bin', 'curl.exe')

# sources
INSTALL_PATH = path(SRC_PATH, 'installers')
CONTENT_PATH = path(SRC_PATH, 'content')
NSISSRC_PATH = path(SRC_PATH, 'nsis')

# download temp
TMP_PATH = path(PWD, 'temp')

# workdirs
MOZ_PATH = path(OUT_PATH, 'mozilla-build')
BIN_PATH = path(MOZ_PATH, 'bin')
PY3_PATH = path(MOZ_PATH, 'python3')
PYSCRPTS = path(PY3_PATH, 'Scripts')

# utilites
Y2J = path(SRC_PATH, 'y2j.exe') # yaml2json pipe tool
P7Z = path(BIN_PATH, '7z.exe' )

#============================================================================
# INSTALLERS INCLUDED

INSTALL_7ZIP  = path(INSTALL_PATH, '7z2107-x64.msi')
INSTALL_NSIS  = path(INSTALL_PATH, 'nsis-3.08.zip')
INSTALL_UPX   = path(INSTALL_PATH, 'upx-3.96-win64.zip')
INSTALL_PY3   = path(INSTALL_PATH, 'python-3.10.2.7z')
INSTALL_UNZ   = path(INSTALL_PATH, 'unz600xN.exe')
INSTALL_ZIP   = path(INSTALL_PATH, 'zip300xN.zip')
INSTALL_EMACS = path(INSTALL_PATH, 'emacs-26.3-x86_64-no-deps.tar.lzma')
INSTALL_KDIFF = path(INSTALL_PATH, 'KDiff3-32bit-Setup_0.9.98.exe')
INSTALL_WATCH = path(INSTALL_PATH, 'watchman-v2021.01.11.00.zip')

#============================================================================
# LOGGING HELPERS


# table of parsed script args
def logopts(title, data):
    algn =      max(list(map(lambda i: len(str(i[0])),             data)))
    line = 17 + max(list(map(lambda i: len(str(i[0]) + str(i[1])), data)))
    def headline(head=('='*line)): return f'{C(WHITE)}#{" " if not head.startswith("=") else ""}{head}\n'
    formatted = '\n'.join( map(lambda i: f'{logchr(":", WHITE)} {C(YELLOW)}{str(i[0]):<{algn}} {logchr(":")} {C(GREEN)}{str(i[1])}', data))
    printl(f'\n{headline()}{headline(title)}{headline()}{formatted}\n{headline()}{C()}')

# section header
def logsection(message): printl(f'\n{C(BOLD, MAGENTA)}# {message}{C()}')

# subheader
def logsubhead(message): logsection(f'{C(MAGENTA)}{message}')

# task prefix:
def logtask(name='task', color=GREEN): return f'{logchr("-")} {C(color)}{name}{logchr(":")}{C()}'

# char (punctuation): dim
def logchr(chrs, color=DIM): return f'{C(color)}{chrs}{C()}'

# source -> target: normal+italic (cyan arrow) white+italic
def logfromto(src=None, dst=None):
    return f'{C(NORMAL, ITALIC)}{(src+" ") if src else ""}'+\
        f'{C(CYAN, BOLD)}->{C()}'+\
        f'{C(WHITE, ITALIC)}{(" "+dst) if dst else ""}{C()}'

# url: underlined cyan
def logurl(url):  return f'{C(CYAN, UNDERLINE)}{url}{C()}'

# colored command line
def logcall(cmd):
    def kvs(arg):
        p = re.match('([^="\\\']+)?([=])?(.*)', arg).groups()
        return f'{p[0] or ""}{logchr(p[1] or "")}{C(ITALIC, GREEN)}{p[2] or ""}'
    def part(arg, i):
        if i == 0:                return f'{C(YELLOW)}{arg}'
        if arg[0:2] == '--':      return f'{logchr(arg[0:2])}{kvs(f"{C(CYAN)}{arg[2:]}")}'
        if arg[0:1] in ['-','+']: return f'{logchr(arg[0:1])}{C(CYAN)}{arg[1:2]}{C(ITALIC,GREEN)}{part(arg[2:],-1)}'
        if arg[0:1] == '/':       return f'{logchr(arg[0:1])}{kvs(f"{C(CYAN)}{arg[1:]}")}'
        if len(arg) == 1:         return f'{C(BOLD, CYAN)}{arg}'
        if '://' in arg:          return f'{logurl(arg)}'
        if os.path.sep in arg:    return f'{C(ITALIC,WHITE)}{arg}'
        return f'{kvs(f"{C(GREEN)}{arg}")}'
    printl(f'{C(WHITE)}$ {sprint(*list(map(part, cmd, range(len(cmd)))))}')

#============================================================================
# TASK HELPERS

#----------------------------------------------------------------------------
# misc

# case insensitive replace
def ireplace(needle, replacement, haystack):
    return re.sub(f'(?i){re.escape(needle)}', lambda m: replacement, haystack)

# return first list item where pred(item) is true
def find(pred, list):
    return reduce((lambda a, b: b if pred(b) else a), list, None)

# chop last "/download" part  from soruce forge urls
# (skip the countdown instersitital)
def get_sourceforge_download(url):
    return dirname(url) if 'sourceforge.net' in url and url.endswith('/download') else url

# hash a string into a hexstring
def hastr(string, hasher): return hasher(string.encode()).hexdigest()

# split 'path/to/filename.ext'
def rootname(path): return os.path.splitext(path)[0] # part before last '.'
def ext(path):      return os.path.splitext(path)[1][1:].lower() # part after

#----------------------------------------------------------------------------
# running sub processe

# call a command w/o output (except on err)
def call(cmd, *popenargs, **kwargs):
    logcall(cmd); void=output(cmd, *popenargs, **kwargs)

# call a command, and let it use stdout
def command(cmd, *popenargs, **kwargs):
    logcall(cmd); printl(f'{C(DIM, YELLOW)}<<<')
    check_call(cmd, *popenargs, **kwargs)
    printl(f'{C(DIM, YELLOW)}>>>')

#----------------------------------------------------------------------------
# file io

# write command ouput to a file
def redirectout(filepath, cmd, *popenargs, **kwargs):
    mkdirs(dirname(filepath)); logcall(cmd + ['>', filepath])
    with open(filepath, 'w') as handle: handle.write(output(cmd, *popenargs, **kwargs))

# read a value form the first line of a file (VERSION etc)
def readfile(path): return chomp(open(path).readline())

# write dedent(content) to a file
def writefile(filepath, content):
    from textwrap import dedent;
    mkdirs(dirname(filepath)); printl(f'{logtask("write")} {logfromto(dst=filepath)}')
    with open(filepath, 'w') as handle: handle.write(dedent(content))

# process file contents with a callback
def procfile(filepath, callback):
    with open(filepath, 'r') as handle: data = handle.read()
    with open(filepath, 'w') as handle: handle.write(callback(data))

#----------------------------------------------------------------------------
# filesystem

# make path (like mkdir -p, accepts multiple paths)
def mkdirs(*pathnames):
    for pathname in pathnames:
        try: os.makedirs(pathname); printl(f'{logtask("mkdir")} {pathname}')
        except: pass

# copy (and optionally rename a file)
def copy(src, dst, name=None):
    filepath = path(dst, basename (name or src)); mkdirs(dst)
    printl(f'{logtask("copy")} {logfromto(src, filepath)}')
    copyfile(src, filepath)

# recursive copy tree
def rcpy(src, dst):
    printl(f'{logtask("copy")} {logfromto(path(src,"**"), path(dst,"**"))}')
    copytree(src, dst)

# recurse walk topdir with callback for each file
def recursedirs(topdir, callback):
    for dirpath, dirnames, files in os.walk(topdir):
        for filename in files: callback(dirpath, dirnames, filename)

# file exists and has some content
def hasfile(path): return os.path.isfile(path) and os.path.getsize(path)

#----------------------------------------------------------------------------
# arhcive handling

# extract a 7z (sfx) archive
def un7ip(archivepath, dst=BIN_PATH):
    mkdirs(dirname(dst)); printl(f'{logtask("un7ip")} {logfromto(archivepath, dst)}')
    # skip '$metadata' paths in self-extracting exes
    skip = ['-x!$*'] if ext(archivepath) == 'exe' else []
    command([P7Z, 'x', archivepath, f'-o{dst}'] + skip)
    return path(dst, rootname(basename(archivepath)))

# unzip an archive
def unzip(archivepath, dst=BIN_PATH):
    mkdirs(dirname(dst)); printl(f'{logtask("unzip")} {logfromto(archivepath, dst)}')
    with ZipFile(archivepath) as zipfile: zipfile.extractall(dst+"\\")
    return path(dst, rootname(basename(archivepath)))

# untar an archive
def untar(archivepath, dst=BIN_PATH):
    mkdirs(dirname(dst)); printl(f'{logtask("untar")} {logfromto(archivepath, dst)}')
    with TarFile(archivepath) as tarfile: tarfile.extractall(dst)
    return path(dst, rootname(basename(archivepath)))

#----------------------------------------------------------------------------
# downloading stuff

# download and cache url using ETag-s
def etag(url, out):
    etag = f'{out}.etag';
    command([REF_CURL, '--etag-compare', etag, '--etag-save', etag,
        '--compressed', '-sNLS#', url, '-o', out])
    return out

# download an url
def curl(url, dst=TMP_PATH, name=None):
    mkdirs(dst); return etag(url, path(dst, basename(name or url)))

# get content from url
def curlout(url, ext=None):
    from hashlib import md5 as hsr
    with open(etag(url,
        f'{path(TMP_PATH, f"{basename(rootname(url))}.{hastr(url, hsr)}")}.{ext or ext(url)}'
    ), 'r') as file: return file.read()

# get parsed json
def curljson(url): return json.loads(curlout(url, 'json'))

# get yaml parsed into json
def curlyaml(url): return json.loads(output([ Y2J ], input=curlout(url, 'yaml')))

# get a latest release from github using a filtering prdicate
def github(owner, repo, pred: lambda asset: bool(asset)):
    url = f'https://api.github.com/repos/{owner}/{repo}/releases/latest'
    printl(f'{logtask("github", YELLOW)} {logurl(url)}'); data = curljson(url)
    app = data['name']     or f'{owner}/{repo}'
    ver = data['tag_name'] or 'latest'
    asset = find(pred, data['assets'])
    if not asset: return None
    printl(f'{logtask("github", YELLOW)} downloading {C(GREEN)}{app}{logchr(":")}{C(CYAN)}{ver}')
    return curl(asset['browser_download_url'], name=asset['name'])

# get a latest version installer from winget manifests
def winget(publisher, package, pred: lambda asset: bool(asset), sanitizeurl=lambda url: url, packagepath=None):
    WINGET_PKGS='https://api.github.com/repos/microsoft/winget-pkgs'
    packagepath=packagepath or f'{publisher[0:1].lower()}/{publisher}/{package}'
    url  = f'{WINGET_PKGS}/contents/manifests/{packagepath}'
    printl(f'{logtask("winget", YELLOW)} {logurl(url)}')
    # return latest version (using a subkey)
    # comparing with the LegacyVersion version parser
    def latest(versions, key='name'): from packaging.version import LegacyVersion as ver; \
        return reduce((lambda a, b: a if ver(a[key]) > ver(b[key]) else b), versions, {key: None})[key]
    # get latest() manifest
    manifest = curlyaml(curljson(
        f'{url}/{latest(curljson(url))}/{publisher}.{package}.installer.yaml'
    )['download_url'])
    app = manifest['PackageIdentifier'] or f'{publisher}.{package}'
    ver = manifest['PackageVersion']    or 'latest'
    asset = find(pred, manifest['Installers'])
    if not asset: return None
    printl(f'{logtask("winget", YELLOW)} downloading {C(GREEN)}{app}{logchr(":")}{C(CYAN)}{ver}')
    return curl(sanitizeurl(asset['InstallerUrl']))

#============================================================================
# PRINT VERSION + PARSED ARGS AS HEADER

VERSION = readfile(path(PWD, 'VERSION'))

logopts(f'{C(BOLD, BLUE)}MozillaBuild PACKAGEIT {logchr(":")} {C(BOLD, MAGENTA)}{VERSION}',
    [
        ('Reference (host) MSYS2 install',  args.msys2_ref_path),
        ('Source location',                 args.source_path),
        ('Staging folder',                  args.staging_path),
        ('MSVC install path',               args.msvc_path),
        ('Latest Windows SDK path',         args.win10_sdk_path),
        ('Download MSYS2 package sources',  args.fetch_sources),
        ('Download latest tool updates',    args.fetch_utils),
        ('Bundle extras with MSYS2',        args.msys_extra),
        ('Bundle devel libs with MSYS2',    args.msys_devel),
        ('Rebuild installer ONLY',          args.nsis_only),
    ]
)

#============================================================================
# PACKINGTIME!

if not NSIS_ONLY:

    #----------------------------------------------------------------------------
    # assert for pacman and curl in referenve MSYS2

    logsection('Check reference MSYS2')
    assert os.path.isfile(REF_PACMAN), f'Reference MSYS2 installation is invalid:\n\t"{REF_PACMAN}" missing'
    assert os.path.isfile(REF_CURL  ), f'Reference MSYS2 installation is invalid:\n\t"{REF_CURL  }" missing'

    #----------------------------------------------------------------------------
    # clear leftovers form previous run

    # We use cmd.exe instead of sh.rmtree because it's more forgiving of open handles than
    # Python is (i.e. not hard-stopping if you happen to have the stage directory open in
    # Windows Explorer while testing.
    if (os.path.exists(OUT_PATH)):
        logsubhead('Removing the previous staging directory')
        call(['cmd.exe', '/C', 'rmdir', '/S', '/Q', OUT_PATH])

    if (FETCH_UTIL == 'no-cache' and os.path.exists(TMP_PATH)):
        logsubhead('Removing the previous temp directory')
        call(['cmd.exe', '/C', 'rmdir', '/S', '/Q', TMP_PATH])

    #----------------------------------------------------------------------------

    logsubhead('Create the working directories')
    mkdirs(TMP_PATH, OUT_PATH, MOZ_PATH, BIN_PATH)

    #----------------------------------------------------------------------------

    logsection('Staging 7-Zip')
    if FETCH_UTIL:
        logsubhead('Trying to fetch latest 7-Zip')
        INSTALL_7ZIP = winget('7zip', '7zip', # get the latest x64 MSI
            lambda installer: installer['Architecture'] == 'x64' and installer['InstallerType'] == 'wix'
        ) or INSTALL_7ZIP

    mkdirs(path(OUT_PATH, '7zip'))

    # Create an administrative install point and copy the files to stage rather
    # than using a silent install to avoid installing the shell extension on the host machine.
    call(['msiexec.exe', '/q', '/a', INSTALL_7ZIP, f'TARGETDIR={path(OUT_PATH, "7zip")}'])

    rcpy(path(OUT_PATH, '7zip', 'Files', '7-Zip'), path(BIN_PATH, '7zip'))
    copy(path(BIN_PATH, '7zip', '7z.exe'), BIN_PATH)
    copy(path(BIN_PATH, '7zip', '7z.dll'), BIN_PATH)

    #----------------------------------------------------------------------------
    # Extract Python3 to the stage directory. The archive being used is the result of running the
    # installer in a VM/SandBox with the command line below and packaging up the resulting directory.
    # Unfortunately, there isn't a way to run a fully isolated install on the host machine without
    # adding a bunch of registry entries, so this is what we're left doing.
    #   <installer> /passive TargetDir=c:\python3 Include_launcher=0 Include_test=0 CompileAll=1 Shortcuts=0
    # Packaged with 7-Zip using:
    #   LZMA2 compression with Ultra compression, 96MB dictionary size, 256 word size, solid archive
    # or from the command line (only need to specify ultra compression here):
    #   $ cd /c/python3 && 7z a /c/temp/python-3.x.x.7z -r . -mx=9

    logsection('Staging Python 3 and extra packages')

    un7ip(INSTALL_PY3, PY3_PATH)
    copy(path(PY3_PATH, 'python.exe'), PY3_PATH, 'python3.exe')

    #----------------------------------------------------------------------------

    logsubhead('Update pip packages')

    PIP_PACKAGES = [
        'pip',
        'setuptools',
        'mercurial',
        'windows-curses',
    ]

    command([path(PY3_PATH, 'python3.exe'), '-m', 'pip', 'install',
        '--ignore-installed' ,'--upgrade', '--no-warn-script-location'
    ] + PIP_PACKAGES)

    #----------------------------------------------------------------------------
    # Find any occurrences of hardcoded interpreter paths in the Scripts directory and change them
    # to a generic python.exe instead. Awful, but distutils hardcodes the interpreter path in the
    # scripts, which breaks because it uses the path on the machine we built this package on, not
    # the machine it was installed on. And unfortunately, pip doesn't have a way to pass down the
    # --executable flag to override this behavior.
    # See http://docs.python.org/distutils/setupscript.html#installing-scripts
    # Do the shebang fix on Python3 too.
    # Need to special-case c:\python3\python.exe too due to the
    # aforementioned packaging issues above.

    logsubhead("distutils shebang fix")

    def shebang_fix(dirpath, dirnames, filename):
        if ext(filename) == 'exe': return
        def fixbang(data): return ireplace('C:\\python3\\python.exe', 'python3.exe',
            ireplace(path(PY3_PATH, 'python3.exe'), 'python3.exe', data))
        procfile(path(dirpath, filename), fixbang)

    recursedirs(PYSCRPTS, shebang_fix)

    #----------------------------------------------------------------------------
    # Extract KDiff3 to the stage directory. The KDiff3 installer doesn't support any sort of
    # silent installation, so we use a ready-to-extract 7-Zip archive instead.

    logsection('Staging KDiff3')
    un7ip(INSTALL_KDIFF, path(MOZ_PATH, 'kdiff3'))

    # note: winget-pkgs has "JoachimEibl/Kiff3":v0.9.98 (points to sourceforge), and a
    # maintained/renamed under "KDE/Kdiff":1.9. form from the original author (points to github)
    # builds: https://binary-factory.kde.org/view/Windows%2064-bit/job/KDiff3_Stable_win64/

    #----------------------------------------------------------------------------

    if not MSYS_EXTRA:
        INFOZIPOUT_PATH = path(BIN_PATH, 'info-zip')

        # Extract Info-Zip Zip & UnZip to the stage directory.
        logsection('Staging Info-Zip')
        unzip(INSTALL_UNZ, INFOZIPOUT_PATH)
        unzip(INSTALL_ZIP, INFOZIPOUT_PATH)

        # Copy unzip.exe and zip.exe to the main bin directory to make our PATH bit more tidy
        copy(path(INFOZIPOUT_PATH, 'unzip.exe'), BIN_PATH)
        copy(path(INFOZIPOUT_PATH, 'zip.exe'), BIN_PATH)

    #----------------------------------------------------------------------------

    if not MSYS_EXTRA:
        logsection('Staging UPX')
        if FETCH_UTIL:
            logsubhead('Trying to fetch latest UPX')
            INSTALL_UPX = github ('upx', 'upx',
                lambda asset: 'win64' in asset['name'].lower()
            ) or INSTALL_UPX

        copy(path(BIN_PATH, unzip(INSTALL_UPX, BIN_PATH), 'upx.exe'), BIN_PATH )

    #----------------------------------------------------------------------------

    logsection('Staging nsinstall')
    copy(path(CONTENT_PATH, 'nsinstall.exe'), BIN_PATH)

    #----------------------------------------------------------------------------

    logsection('Staging vswhere')
    if FETCH_UTIL:
        logsubhead('Trying to fetch an latest vswhere')
        VSWHERE = github('microsoft', 'vswhere',
            lambda asset: ext(asset['name']) == 'exe'
        ) or VSWHERE

    copy(VSWHERE, BIN_PATH)

    #----------------------------------------------------------------------------

    logsection('Staging watchman')
    unzip(INSTALL_WATCH, BIN_PATH)

    # copy license
    copy(path(CONTENT_PATH, 'watchman-LICENSE'), BIN_PATH)

    #----------------------------------------------------------------------------

    logsection('Locating MSYS2 components and dependencies')

    BASE_PKGS = [ 'msys2-runtime' ] + ([ 'pacman' ] if MSYS_EXTRA else [])

    REQD_PKGS = [
        'bash-completion',
        'diffutils',
        'file',
        'filesystem',
        'gawk',
        'grep',
        'm4',
        'man-db',
        'mintty',
        'nano',
        'openssh',
        'patch',
        'perl',
        'tar',
        'vim',
        'wget',
    ] + ([ # these are installed with pacman on MSYS_EXTRA == True
        'bash',
        'bzip2',
        'ca-certificates',
        'coreutils',
        'findutils',
        'gzip',
        'info',
        'less',
        'sed',
        'which',
        'xz',
        'zstd',
    ] if not MSYS_EXTRA else [])

    # extra packages available in msys base repo
    EXTRA_PKGS = [
        'pkgconf',  # install pkg-config for mach --with-system-LIBX
        'emacs',    # tbh: i have not compared this to the tar.gz
        'zip',
        'unzip',
        'upx',      # installs ucl compression algo a a separate package
        # kdiff3 ?
    ]

    # optinally useful: developer libs in msys base repo
    DEVEL_PKGS = [
        'icu-devel',
        'libevent-devel',
        'libffi-devel',
        'zlib-devel',
        # nspr ?
        # libpng ?
        # icu4x ?
    ]

    #----------------------------------------------------------------------------
    # Extract MSYS2 packages to the stage directory

    logsection('Syncing base MSYS2 components')

    MSYS2_PATH = path(MOZ_PATH, 'msys2')
    mkdirs(path(MSYS2_PATH, 'tmp'),
           path(MSYS2_PATH, 'var', 'lib', 'pacman'),
           path(MSYS2_PATH, 'var', 'log'))

    MSYS2_ETC  = path(MSYS2_PATH, 'etc')
    MSYS2_USR  = path(MSYS2_PATH, 'usr')
    MSYS2_UBIN = path(MSYS2_USR,  'bin')

    MSYS2_ENV = os.environ.copy()
    MSYS2_ENV['PATH'] = os.pathsep.join([path(REF_PATH, 'usr', 'bin'), MSYS2_ENV['PATH']])

    #----------------------------------------------------------------------------
    # function to call pacman in the staging root
    # using a wrapper to execute the cmd / capture the output

    def pacman(args=[], cmd='S', env=MSYS2_ENV, wrap_call=command):
        wrap_call([REF_PACMAN, f'-{cmd}', '--noconfirm', '--root', MSYS2_PATH] + args, env=env)

    #----------------------------------------------------------------------------
    # Install msys2-runtime (and pacman if opted) first
    # so that post-install scripts run successfully

    pacman(['--refresh'] + BASE_PKGS);
    pacman(REQD_PKGS)
    if MSYS_EXTRA: logsubhead('Syncing extra MSYS2 packages'); pacman(EXTRA_PKGS)
    if MSYS_DEVEL: logsubhead('Syncing developer MSYS2 library packages'); pacman(DEVEL_PKGS)

    #----------------------------------------------------------------------------

    if FETCH_SRCS:
        logsubhead('Downloading MSYS2 package sources')
        OUT_SRC_PATH = path(OUT_PATH, 'src'); mkdirs(OUT_SRC_PATH)
        command([REF_CURL, '-sLS#', '--remote-name-all'] + ([
            f'https://repo.msys2.org/msys/sources/{name}-{version}.src.tar.gz'
            for name, version in (line.split(' ') for line in pacman(cmd='Q', wrap_call=output).splitlines())
        ]), cwd=OUT_SRC_PATH)

    #----------------------------------------------------------------------------

    if not MSYS_EXTRA:
        # Extract emacs to the stage directory
        # TBH: untested
        logsection('Staging emacs')
        untar(INSTALL_EMACS, path(MSYS2_PATH, 'usr'))

    #----------------------------------------------------------------------------

    logsection('Replacing MSYS rm with winrm')
    copy(path(MSYS2_UBIN,   'rm.exe'),    MSYS2_UBIN, 'rm-msys.exe')
    copy(path(CONTENT_PATH, 'winrm.exe'), MSYS2_UBIN, 'rm.exe')
    copy(path(CONTENT_PATH, 'winrm.exe'), MSYS2_UBIN, 'winrm.exe')

    #----------------------------------------------------------------------------
    # Recursively find all MSYS DLLs, then chmod them to make sure none are read-only.
    # Then rebase them via the editbin tool.

    logsection('Collecting staged MSYS DLL-s for rebasing')

    msys_dlls = {}

    def collect_dlls(dirpath, dirnames, filename):
        if ext(filename) != 'dll': return
        filepath = path(dirpath, filename); os.chmod(filepath, 0o755)
        # "msys-perl5_32.dll" is in both "/usr/bin/" and "/usr/lib/perl5/...".
        # Since "editbin /rebase" fails if it's provided equivalent dlls, let's
        # ensure no two dlls with the same name are added.
        if filename in msys_dlls: return
        msys_dlls[filename] = os.path.relpath(filepath, MSYS2_PATH)

    recursedirs(MSYS2_PATH, collect_dlls)

    #----------------------------------------------------------------------------

    logsubhead('Rebasing collected DLL-s')

    tools_version=readfile(path(MSVC_PATH, 'VC', 'Auxiliary', 'Build', 'Microsoft.VCToolsVersion.default.txt'))
    EDITBIN=path(MSVC_PATH, 'VC', 'Tools', 'MSVC', tools_version, 'bin', 'HostX64', 'x64', 'editbin.exe')

    def editbin(file_list, base, cwd=None):
        check_call([EDITBIN, '/NOLOGO', '/REBASE:BASE=' + base, '/DYNAMICBASE:NO'] + file_list, cwd=cwd)

    # rebase collected DLLS
    editbin(list(msys_dlls.values()), '0x60000000,DOWN', MSYS2_PATH)

    # msys-2.0.dll is special and needs to be rebased independent of the rest
    editbin([path(MSYS2_UBIN, 'msys-2.0.dll')], '0x60100000')

    #----------------------------------------------------------------------------
    # Embed some fiendly manifests to make UAC happy.

    logsection('Embedding UAC-friendly manifests in executable files')
    def embed_mainfest(dirpath, dirnames, filename):
        if ext(filename) != 'exe': return
        check_call([path(WSDK_PATH, 'mt.exe'), '-nologo',
            '-manifest', path(SRC_PATH, 'noprivs.manifest'),
            f'-outputresource:{path(dirpath, filename)};#1'
        ])

    recursedirs(MSYS2_PATH, embed_mainfest)

    #----------------------------------------------------------------------------

    logsection('Configure staged MSYS')

    # db_home: Set "~" to point to "%USERPROFILE%"
    # db_gecos: Fills out gecos information (such as the user's full name) from AD/SAM.
    writefile(path(MSYS2_ETC, 'nsswitch.conf'),
        """
        db_home: windows
        db_gecos: windows
        """
    )

    # vi/vim wrapper
    writefile(path(MSYS2_UBIN, 'vi'),
        """
        #!/bin/sh
        exec vim "$@"
        """
    )

    if not MSYS_EXTRA:
        # we didn't include the package manager (pacman),
        # so remove its key management setup.
        try: os.remove(path(MSYS2_ETC, 'post-install', '07-pacman-key.post'))
        except: pass

    # We didn't install the xmlcatalog binary.
    try: os.remove(path(MSYS2_ETC, 'post-install', '08-xml-catalog.post'))
    except: pass

    #----------------------------------------------------------------------------

    # Copy various configuration files.
    logsubhead('Copying configuration files')

    copy(path(PWD, 'VERSION'), MOZ_PATH)

    copy(path(MSYS2_ETC, 'skel', '.inputrc'), MSYS2_ETC, 'inputrc')

    copy(path(CONTENT_PATH, 'mercurial.ini'  ), PYSCRPTS)
    copy(path(CONTENT_PATH, 'start-shell.bat'), MOZ_PATH)
    copy(path(CONTENT_PATH, 'msys-config', 'ssh_config'        ), path(MSYS2_ETC, 'ssh'))
    copy(path(CONTENT_PATH, 'msys-config', 'profile-mozilla.sh'), path(MSYS2_ETC, 'profile.d'))

    #----------------------------------------------------------------------------

    logsubhead('Installing bash-completion helpers')
    COMPLETIONS = path(MSYS2_USR, 'share', 'bash-completion', 'completions')

    curl('https://www.mercurial-scm.org/repo/hg/raw-file/tip/contrib/bash_completion', COMPLETIONS, 'hg')

    ## FIXME: umm, this one is wwaayy ssllooww to respond :/
    ## -> tested on a hg clone of mozilla-unified, with an i7-9750H (6x2 cores) + ON A SSD
    # curl('https://hg.mozilla.org/mozilla-unified/raw-file/tip/python/mach/bash-completion.sh', COMPLETIONS, 'mach')
    ## and the script generated by 'mach mach-autocomplete bash' seems to be source root specific :/

    ## FIXME: not needed (?) (as the preferred way of running pip should be with 'mach python -m pip' in a source root)
    # redirout([path(PY3_PATH, 'python3.exe'), '-m', 'pip', 'completion', '--bash'], path(COMPLETIONS, 'pip'))
    # shebang_fix(dirpath=COMPLETIONS, filename='pip')

    ## FIXME: maybe 'pip competion --bash' and 'rustup complete bash' etc can go into post ?

#============================================================================
# ALL STAGED, LETS PACKAGEIT!

logsection('Packaging with NSIS')
if FETCH_UTIL:
    logsubhead('Trying to fetch latest NSIS')
    INSTALL_NSIS = winget( 'NSIS', 'NSIS',
        lambda installer: installer['Architecture'] == 'x86',
        lambda url: get_sourceforge_download(url).replace('-setup.exe', '.zip')
    ) or INSTALL_NSIS

logsubhead('Unzipping NSIS tools')
NSISOUT_PATH = unzip(INSTALL_NSIS, OUT_PATH)

#----------------------------------------------------------------------------

logsubhead('Prepping installer scripts')

INSTALLER_NSI = 'installit.nsi'
LICENSE_FILE  = 'license.rtf'

copy(path(NSISSRC_PATH, 'setup.ico'), OUT_PATH)
copy(path(NSISSRC_PATH, 'helpers.nsi'), OUT_PATH)
copy(path(NSISSRC_PATH, 'mozillabuild.bmp'), OUT_PATH)

def replaceversion(data:str) -> str:
    return data.replace('@VERSION@', VERSION)

copy(path(NSISSRC_PATH, LICENSE_FILE), OUT_PATH)
procfile(path(OUT_PATH, LICENSE_FILE), replaceversion)
copy(path(OUT_PATH, LICENSE_FILE), MOZ_PATH)

copy(path(NSISSRC_PATH, INSTALLER_NSI), OUT_PATH)
procfile(path(OUT_PATH, INSTALLER_NSI), replaceversion)

#----------------------------------------------------------------------------

logsubhead('Packaging with NSIS...')
command([path(OUT_PATH, NSISOUT_PATH, 'makensis.exe'), '/NOCD', INSTALLER_NSI], cwd=OUT_PATH)

#============================================================================

logsection(f'PACKAGING MozillaBuild v{VERSION} {C(DIM, GREEN, YELLOW+BGR, INV)} DONE! {C()}')

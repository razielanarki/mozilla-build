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

import functools
import os, stat, re, json, hashlib, typing
from typing import Any, Callable, Iterable, Optional, Text, Union
from winreg import OpenKey, HKEY_LOCAL_MACHINE as HKLM, HKEY_CURRENT_USER as HKCU, QueryValueEx, QueryInfoKey, EnumKey
from shutil import copyfile, copytree, register_unpack_format, unpack_archive
from os.path import join as path, dirname, basename, abspath, isdir
from argparse import ArgumentParser
from subprocess import DEVNULL, run, CalledProcessError
from textwrap import dedent
from functools import reduce
from packaging.version import LegacyVersion as Version

#============================================================================
# USAGE

SYS = path('C:\\')
PWD = abspath(dirname(__file__))


args = ArgumentParser()
args.add_argument(
    '-s', '--sources-path',
    dest='SRC_PATH', default=path(PWD, 'sources'),
    help='Path to source directory for bundled tools and cfg',
)
args.add_argument(
    '-m', '--msys2-ref-path',
    dest='REF_PATH', # # default=msys2_path(),
    help='Path to reference MSYS2 installation (containing curl and pacman)',
)
args.add_argument(
    '-o', '--staging-path',
    dest='OUT_PATH', default=path(PWD, 'stage'),
    help='Path to desired staging directory'
)
args.add_argument(
    '-v', '--msvc-path',
    dest='MSVC_PATH', # default=vswhere('installationPath'),
    help='Path to Visual Studio installation',
)
args.add_argument(
    '-w', '--win10-sdk-path',
    dest='SDK_PATH', # default=sdkpath(),
    help='Path to Windows 10 SDK installation folder'
)
args.add_argument(
    '-f', '--fetch-sources', action='store_true',
    dest='FETCH_SOURCES', default=False,
    help=f'Download MSYS2 packags sources to "{path("cfg.OUT_PATH", "src")}"',
)
args.add_argument(
    '-u', '--fetch-tools', nargs='?', choices=['with-cache', 'without-cache'],
    dest='FETCH_TOOLS', default=('MOZ_DEV' in os.environ.keys()),
    help=f'Download latest tool updates to "{path("PWD", "temp")}", and bundle them.',
)
args.add_argument(
    '-p', '--msys-pacman', action='store_true',
    dest='MSYS_PACMAN', default=('MOZ_DEV' in os.environ.keys()),
    help='Bundle pacman from the MSYS2 base repo',
)
args.add_argument(
    '-x', '--msys-extra', action='store_true',
    dest='MSYS_EXTRA', default=('MOZ_DEV' in os.environ.keys()),
    help='Bundle pkg-config, info-zip and upx from the MSYS2 base repo',
)
args.add_argument(
    '--msys-devel', action='store_true',
    dest='MSYS_DEVEL', default=False,
    help='Bundle libicu4c-devel, libffi-devel, libevent-devel and zlib-devel from MSYS2',
)

#============================================================================
# type hintig

T=typing.TypeVar('T')
Sgr=int
Url=Path=str
Cmd=Iterable[str]
# for return types
Maybe=Optional
Json=Any

#============================================================================
# OUTPUT

# STYLE
BOLD=1; DIM=2; ITALIC=3; UNDERLINE=4; REVERSED=7
# COLOR
DARK=30; RED=31; GREEN=32; YELLOW=33; BLUE=34; MAGENTA=35; CYAN=36; WHITE=37
BGR=+10

# color. colored text
def sgr(*gr:Sgr) -> Text:
    return f'\033[;{";".join(map(nuls, gr))}m'

# dont print false-y thing
def nuls(arg:Any, nul:Text='', fmt:Text='{}') -> Text:
    return str(arg and fmt.format(arg) or nul)

# wrap a piece of text with ansi sgr
def fmt(arg:Any, *gr:Sgr, **kwargs:Any) -> Text:
    return f'{sgr(*gr)}{nuls(arg, **kwargs)}{sgr()}'

#============================================================================
# print raw tty print

# print text with ansi sgr colors
def println(*args:Any):
    os.system('color')
    print(*args, flush=True)

# perl-like chomp: eats last newline\carriage feed pair
def chomp(text:Text) -> Text:
    return re.sub('(\n\r?|\r\n?)$', '', text, 1)

# run a subprocess
def subproc(cmd:Cmd, **kwargs:Any):
    try: return run(args=cmd, check=True,
                    text=True, encoding='UTF-8', **kwargs)
    except CalledProcessError as error:
        logerror(os.linesep.join(map(nuls, [error.stdout, error.stderr])),
                 error.returncode)
        raise

# capture command output
# print (uncaptured) error message + throw on failure
def output(cmd:Cmd, **kwargs:Any):
    return chomp(subproc(cmd, **kwargs, capture_output=True).stdout)

#============================================================================
# PARSE ARGS

# guess msys path: check default or guess from registry
def msyspath():
    # default MSYS2 install path
    msyspath=path(SYS, 'msys64')

    # if not found in the default location, try to find it using the registry
    if not isdir(msyspath): # not in default location: check registry for (un)installer info
        with OpenKey(HKCU, path('SOFTWARE', 'Microsoft', 'Windows', 'CurrentVersion', 'Uninstall')) as hkey:
            for index in range(0, QueryInfoKey(hkey)[0]):
                with OpenKey(hkey, EnumKey(hkey, index)) as hsubkey:
                    if QueryValueEx(hsubkey, "DisplayName")[0] == "MSYS2 64bit":
                        msyspath = QueryValueEx(hsubkey, "InstallLocation")[0]
                        break

    # still not found: check if /path/to/msys64 is in the PATH (eg: Chocolatey)
    if not os.path.isdir(msyspath):
        for envpath in os.environ["PATH"].split(os.pathsep):
            dllpath = os.path.join(envpath, "usr", "bin", "msys-2.0.dll")
            if os.path.isfile(dllpath):
                with open(dllpath, "rb") as f:
                    f.seek(60)
                    f.seek(struct.unpack("<L", f.read(4))[0] + 4)
                    if 0x8664 == struct.unpack("<H", f.read(2))[0]:
                        msyspath = envpath
                        break

    return msyspath

# query a property of latest msvc/prerelease/buildtools installed
def vswhere(property:str) -> Path:
    return output([path(os.getcwd(), 'sources', 'vswhere.exe'),
                   '-products', '*', '-latest', '-prerelease',
                   '-format', 'value', '-utf8', '-property', property])

# detect winsdk path
def sdkpath() -> Path:
    with OpenKey(HKLM, path('SOFTWARE', 'WOW6432Node', 'Microsoft', 'Microsoft SDKs', 'Windows', 'v10.0')) as hkey:
        sdk = QueryValueEx(hkey, 'InstallationFolder')[0]
        ver = QueryValueEx(hkey, 'ProductVersion')[0]

    return path(sdk, 'bin', f'{ver}.0', 'x64')

args.set_defaults(
    REF_PATH  = msyspath(),
    MSVC_PATH = vswhere('installationPath'),
    SDK_PATH  = sdkpath()
)

parsed = args.parse_args()

SRC_PATH      = parsed.SRC_PATH
REF_PATH      = parsed.REF_PATH
OUT_PATH      = parsed.OUT_PATH
MSVC_PATH     = parsed.MSVC_PATH
SDK_PATH      = parsed.SDK_PATH
MSYS_PACMAN   = parsed.MSYS_PACMAN
MSYS_EXTRA    = parsed.MSYS_EXTRA
MSYS_DEVEL    = parsed.MSYS_DEVEL
FETCH_SOURCES = parsed.FETCH_SOURCES
FETCH_TOOLS   = parsed.FETCH_TOOLS

#============================================================================
# SUPPLEMENTARY CONFIG

# requred binaries from mreferenced MSYS
REF_PACMAN = path(REF_PATH, 'usr', 'bin', 'pacman.exe')
REF_CURL   = path(REF_PATH, 'usr', 'bin', 'curl.exe')

# sources
INSTALL_PATH = path(SRC_PATH, 'installers')
CONTENT_PATH = path(SRC_PATH, 'content')
NSISSRC_PATH = path(SRC_PATH, 'nsis')

# downloads dir
CURL_PATH = path(PWD, 'downloaded')
ETAG_PATH = path(CURL_PATH, 'cache')

# workdirs
MOZ_PATH = path(OUT_PATH, 'mozilla-build')
BIN_PATH = path(MOZ_PATH, 'bin')
PY3_PATH = path(MOZ_PATH, 'python3')
PYSCRPTS = path(PY3_PATH, 'Scripts')

# utilites
VSWHERE  = path(SRC_PATH, 'vswhere.exe')
YML2JSON = path(SRC_PATH, 'y2j.exe')
UN7IP    = path(BIN_PATH, '7z.exe' )

# base urls of services used
GITHUB_API  = f'https://api.github.com/repos'
WINGET_PKGS = f'{GITHUB_API}/microsoft/winget-pkgs'

#============================================================================
# INSTALLERS INCLUDED

INSTALL_7ZIP  = path(INSTALL_PATH, '7z2107-x64.msi')
INSTALL_NSIS  = path(INSTALL_PATH, 'nsis-3.08.zip')
INSTALL_UPX   = path(INSTALL_PATH, 'upx-3.96-win64.zip')
INSTALL_PY3   = path(INSTALL_PATH, 'python-3.10.4.7z')
INSTALL_UNZ   = path(INSTALL_PATH, 'unz600xN.exe')
INSTALL_ZIP   = path(INSTALL_PATH, 'zip300xN.zip')
INSTALL_EMACS = path(INSTALL_PATH, 'emacs-26.3-x86_64-no-deps.tar.lzma')
INSTALL_KDIFF = path(INSTALL_PATH, 'KDiff3-32bit-Setup_0.9.98.exe')
INSTALL_WATCH = path(INSTALL_PATH, 'watchman-v2021.01.11.00.zip')

#============================================================================
# LOGGING

#----------------------------------------------------------------------------
# formatters

# format punctuation chars as dim
def chf(chrs:Text, *color:Sgr) -> Text:
    return fmt(chrs, *color or [DIM]) if chrs else ''

# format a move 'src -> dist' op
def opf(src:Path=None, dst:Path=None) -> Text:
    return ''.join([fmt(src, fmt='{} '), fmt('->', CYAN),
                    fmt(dst, WHITE, fmt=' {}')])

# format colored task prefix
def taskf(name:Text='task', *color:Sgr) -> Text:
    return ''.join([chf('-'),fmt(name, *color or [GREEN]),chf(':')])

# format url as underlined cyan
def urlf(url:Url) -> Text:
    return fmt(url, CYAN, UNDERLINE)

#----------------------------------------------------------------------------
# loggers

# status messages
def logstatus(pre:Text, bg:Sgr, text:Text, code:Any=None, tpl:Text=' {} '):
    println(pre, fmt(nuls(code, fmt=tpl), DIM, bg, YELLOW+BGR, REVERSED), text)

def logsuccess(text:Text, code:Any='DONE'): logstatus('-', GREEN, text, code)
def logerror(text:Text, code:Any='ERROR'): logstatus('!', RED, text, code)

# table of parsed script args
def logheader(text:Text, arginfo:list[tuple[Text,Any]]):
    width = max(map(len,[label              for (label, skip ) in arginfo]))
    total = max(map(len,[label + str(value) for (label, value) in arginfo]))
    boxln = fmt('#'+('='*total), WHITE)

    println(os.linesep.join([
        boxln, fmt('# '+text, WHITE),
        boxln, *(' '.join([chf(':', WHITE), fmt(label.ljust(width), YELLOW),
                           chf(':'), fmt(str(value), GREEN)])
                for (label, value) in arginfo),
        boxln]))

# section header, subheader
def logsection(text:Text):
    println(fmt(f'{os.linesep}# {text}', BOLD, MAGENTA))

def logsubhead(text:Text):
    logsection(fmt(text, MAGENTA))

# colored command line
def logcall(cmd:Cmd):
    def argvf(arg:str) -> str:
        key, eq, value = re.match('([^="\\\']+)?([=])?(.*)', arg).groups()
        return ''.join([key, chf(eq), fmt(value, ITALIC, GREEN)])

    def argf(arg:str, i:int, p:int=0) -> str:
        if i == 0:                return fmt(arg, YELLOW)
        if arg[0:2] == '--':      return ''.join([chf(arg[0:2]), argvf(fmt(arg[2:], CYAN))])
        if arg[0:1] in ['-','+']: return ''.join(['' if p > 0 else chf(arg[0:1]), fmt(arg[p+1:p+2],CYAN), fmt(argf(arg,i,p+1), ITALIC,GREEN) if p < len(arg) else ''])
        if arg[0:1] == '/':       return ''.join([chf(arg[0:1]), argvf(fmt(arg[1:], CYAN))])
        if len(arg) == 1:         return fmt(arg, BOLD, CYAN)
        if '://' in arg:          return urlf(arg)
        if os.path.sep in arg:    return argvf(fmt(arg, ITALIC, WHITE))
        return argvf(fmt(arg, GREEN))

    println(fmt('$', WHITE), *map(argf, map(nuls,cmd), range(len(cmd))))

#============================================================================
# MISC

# return first list item where pred(item) is true
def find(pred:Callable[[T],bool], seq:list[T]) -> T:
    for b in seq: print(pred(b), b)
    return reduce(lambda a, b: b if pred(b) else a, seq)

# chop last "/download" part  from soruce forge urls
# (skip the countdown instersitital)
def sourceforge_url(url:Url) -> Url:
    return (dirname(url)
            if 'sourceforge.net' in url and url.endswith('/download')
            else url)

def rootname(path:Path) -> Path:
    """Returns full path name without the extension."""
    return os.path.splitext(path)[0]

def ext(path:Path) -> Path:
    """Returns just  the extension of a ful path name."""
    return os.path.splitext(path)[1][1:]

#============================================================================
# PROCESSES

# call a command w/o output (except on err)
def call(cmd:Cmd, **kwargs:Any):
    logcall(cmd)
    subproc(cmd, **kwargs)

# call a command, and let it use stdout
def command(cmd:Cmd, **kwargs:Any):
    logcall(cmd)
    println(fmt('<<<', DIM, YELLOW))
    subproc(cmd, **kwargs)
    println(fmt('>>>', DIM, YELLOW))

#============================================================================
# I/O

def getcontents(path:Path) -> Text:
    """Read a file into a string buffer, stripping the last newline"""
    with open(path, 'r') as handle: return chomp(handle.read())

def putcontents(path:Path, text:Text):
    """Writes a text buffer intoto a file"""
    with open(path, 'w') as handle: handle.write(text)

# process file contents with a callback
def modcontents(path:Path, mod:Callable[[Text], Text]=str):
    """Process file contents using a callback"""
    putcontents(path, mod(getcontents(path)))

# write command ouput to a file
def pipeto(cmd:Cmd, path:Path, **kwargs:Any):
    mkdirs(dirname(path))
    logcall(cmd + ['>', path])
    putcontents(path, output(cmd, **kwargs))

#============================================================================
# FILESYSTEM HELPERS

# make paths (like mkdir -p)
def mkdirs(*paths:Path):
    for path in paths:
        try: # first, try to make the path:
            os.makedirs(path) # fails if already exists, and if not:
            println(taskf("mkdir"), path) # log the dir creation
        except: pass

# copy (and optionally rename a file)
def copy(src:Path, dst:Path, name:Path=None):
    filepath = path(dst, name or basename (src))
    mkdirs(dst)
    println(taskf("copy"), opf(src, filepath))
    copyfile(src, filepath)

# recursive copy tree
def copydir(src:Path, dst:Path):
    println(taskf("copy -r"), opf(src, dst))
    copytree(src, dst)

# recursively remove directory tree (rm -rf)
# We use cmd.exe instead of sh.rmtree because it's more forgiving of open handles than
# Python is (i.e. not hard-stopping if you happen to have the stage directory open in
# Windows Explorer while testing.
def rmdir(path:Path):
    call(['cmd.exe', '/C', 'rmdir', '/S', '/Q', os.path.normpath(path)])

# wrap os.walk to call a calback on each file
def withfilesin(top:Path, do:Callable[[Path], None]=lambda:None):
    for dirpath, dirnames, filenames in os.walk(top):
        for filename in filenames: do(path(dirpath, filename))

# file exists and has some content
def filenotempty(path:Path) -> bool:
    return os.path.isfile(path) and os.path.getsize(path)

#============================================================================
# arhcive unpacking

# register 7z as an unpacker
def un7pak(archive:Path, dst:Path=BIN_PATH):
    # skip installer metadata in uppacking exes
    skip = ['-x!$*'] if ext(archive) == 'exe' else []
    command([UN7IP, 'x', archive, f'-o{dst}'] + skip)

register_unpack_format('7zip', ['7z', 'exe'], un7pak)

# unpack an archive, return path to extracted folder
def unpack(archive:Path, dst:Path=BIN_PATH, fmt:str=None) -> Path:
    mkdirs(dirname(dst))
    println(taskf("unpack"), opf(archive, dst))
    unpack_archive(archive, dst, fmt)
    return path(dst, rootname(basename(archive)))

#----------------------------------------------------------------------------
# downloading stuff

# download and cache url using ETag-s, returns the out path
def etag(url:Url, out:Path) -> Path:
    etag = f'{path(ETAG_PATH, basename(out or url))}.etag'
    command([REF_CURL,
             '--etag-compare', etag, '--etag-save', etag,
             '--compressed', '-sNLS#', url, '-o', out])
    return out

# download an url, return tmp path
def curl(url:Url, name:Path=None) -> Path:
    return etag(url, path(CURL_PATH, basename(name or url)))

# download a file, and save it as 'dst'
def download(url:Url, dst:Path) -> Path:
    return etag(url, dst)

# get content from url
def geturl(url:Url, type:Path=None) -> Text:
    return getcontents(curl(url, basename(os.extsep.join([
        rootname(url), hashlib.md5(url.encode()).hexdigest(),
        type or ext(url)]))))

# download url as json
def getjson(url:Url) -> Json:
    return json.loads(geturl(url, 'json'))

# download url as yaml translated into json
def getyml(url:Url) -> Json:
    return json.loads(output([ YML2JSON ], input=geturl(url, 'yaml')))

# get a latest release from github
def github(owner:str, repo:str,
           pred:Callable[...,bool]) -> Maybe[Path]:
    url = f'{GITHUB_API}/{owner}/{repo}/releases/latest'
    println(taskf('github', YELLOW), urlf(url))

    data = getjson(url)

    if not (asset := find(pred, data['assets'])):
        return logerror('no suitable assets found')

    app = data['name']     or f'{owner}/{repo}'
    ver = data['tag_name'] or 'latest'

    println(taskf('download'), fmt(app, GREEN), fmt(ver, CYAN))
    return curl(asset['browser_download_url'], name=asset['name'])

# get a latest version installer from winget manifests
def winget(publisher:str, package:str,
           pred:Callable[...,bool],
           sanitizeurl:Callable[[Url],Url]=str,
           packagepath:Url=None) -> Maybe[Path]:
    packagepath=(packagepath or
                 '/'.join([publisher[0:1].lower(), publisher, package]))
    url  = f'{WINGET_PKGS}/contents/manifests/{packagepath}'
    println(taskf('winget', YELLOW), urlf(url))

    # return latest version (comparing on a subkey)
    # comparing with the LegacyVersion version parser
    def latest(versions:list[dict[Text,Any]], key='name') -> Text:
        return max(map(lambda item: Version(item[key]), versions))

    # get manifest for the latest version
    manifest = getyml(getjson(
        f'{url}/{latest(getjson(url))}/{publisher}.{package}.installer.yaml'
    )['download_url'])

    if not (asset := find(pred, manifest['Installers'])):
        return logerror('no suitable assets found')

    app = manifest['PackageIdentifier'] or f'{publisher}.{package}'
    ver = manifest['PackageVersion']    or 'latest'

    println(taskf('download'), fmt(app, GREEN), fmt(ver, CYAN))
    return curl(url=sanitizeurl(asset['InstallerUrl']))

#============================================================================
# PRINT VERSION + PARSED ARGS AS HEADER

VERSION = getcontents(path(PWD, 'VERSION'))

logheader(
    ' '.join([fmt('MozillaBuild PACKAGEIT', BOLD, BLUE),
              chf(':'), fmt(VERSION, BOLD, MAGENTA)]),
    [
        ('Reference (host) MSYS2 install',  REF_PATH),
        ('Source location',                 SRC_PATH),
        ('Staging folder',                  OUT_PATH),
        ('MSVC install path',               MSVC_PATH),
        ('Latest Windows 10 SDK path',      SDK_PATH),
        ('Download MSYS2 package sources',  FETCH_SOURCES),
        ('Download latest tool updates',    FETCH_TOOLS),
        ('Bundle extras with MSYS2',        MSYS_EXTRA),
        ('Bundle devel libs with MSYS2',    MSYS_DEVEL),
    ]
)

#============================================================================
# PACKINGTIME!
#----------------------------------------------------------------------------

# assert for pacman and curl in referenve MSYS2
logsection('Check reference MSYS2')
assert os.path.isfile(REF_PACMAN), f'Reference MSYS2 installation is invalid:\n\t"{REF_PACMAN}" missing'
assert os.path.isfile(REF_CURL  ), f'Reference MSYS2 installation is invalid:\n\t"{REF_CURL  }" missing'
logsuccess('pacman and curl present')

#----------------------------------------------------------------------------

# clear leftovers form previous run
if (os.path.exists(OUT_PATH)):
    logsubhead('Removing the previous staging directory')
    rmdir(OUT_PATH)

# clear the download cache if reqd
if (FETCH_TOOLS == 'no-cache' and os.path.exists(CURL_PATH)):
    logsubhead('Removing the previous temp directory')
    rmdir(CURL_PATH)

#----------------------------------------------------------------------------

logsubhead('Creating working directories')
mkdirs(ETAG_PATH, OUT_PATH, MOZ_PATH, BIN_PATH)

#----------------------------------------------------------------------------

OUT_7ZIP=path(OUT_PATH, '7zip')
BIN_7ZIP=path(BIN_PATH, '7zip')

if FETCH_TOOLS:
    logsubhead('Trying to fetch latest 7-Zip')
    INSTALL_7ZIP = winget('7zip', '7zip', # get the latest x64 MSI
        lambda installer: (installer['Architecture'] == 'x64' and
                           installer['InstallerType'] == 'wix')
    ) or INSTALL_7ZIP

logsection('Staging 7-Zip')
mkdirs(OUT_7ZIP)

# Create an administrative install point and copy the files to stage rather
# than using a silent install to avoid installing the shell extension on the host machine.
call(['msiexec.exe', '/q', '/a', INSTALL_7ZIP, f'TARGETDIR={OUT_7ZIP}'])

# copy files
copydir(path(OUT_7ZIP, 'Files', '7-Zip'), BIN_7ZIP)
copy(path(BIN_7ZIP, '7z.exe'), BIN_PATH)
copy(path(BIN_7ZIP, '7z.dll'), BIN_PATH)

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

unpack(INSTALL_PY3, PY3_PATH)
copy(path(PY3_PATH, 'python.exe'), PY3_PATH, 'python3.exe')

#----------------------------------------------------------------------------

logsubhead('Update pip packages')

PIP_PACKAGES = [
    'pip',
    'setuptools',
    'mercurial',
    'windows-curses',
]

command([
    path(PY3_PATH, 'python3.exe'), '-m', 'pip', 'install',
    '--ignore-installed', '--upgrade', '--no-warn-script-location',
    *PIP_PACKAGES
])

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

logsubhead('distutils shebang fix')

FIX_BANGS=map(re.escape, [
    path(SYS, 'python3', 'python.exe'),
    path(PY3_PATH, "python3.exe")
])

def shebang_fix(filename:Path):
    if ext(filename) == 'exe': return
    modcontents(filename, lambda contents: reduce(lambda data, bang:
            re.sub(bang, 'python3.exe', data, 1, flags=re.IGNORECASE),
        FIX_BANGS, contents))

withfilesin(PYSCRPTS, do=shebang_fix)

#----------------------------------------------------------------------------
# Extract KDiff3 to the stage directory. The KDiff3 installer doesn't support
# silent installation, so we use a ready-to-extract 7-Zip archive instead.

logsection('Staging KDiff3')
unpack(INSTALL_KDIFF, path(MOZ_PATH, 'kdiff3'))

# note: winget-pkgs has
# - "JoachimEibl/Kiff3":v0.9.98 (links to sourceforge),
# - "KDE/Kdiff":1.9.x (links to github)
#    form from the original author, available in KDE / on windows at
#    https://binary-factory.kde.org/view/Windows%2064-bit/job/KDiff3_Stable_win64/

#----------------------------------------------------------------------------

if not MSYS_EXTRA:
    INFOZIP_OUT_PATH = path(BIN_PATH, 'info-zip')

    # Extract Info-Zip Zip & UnZip to the stage directory.
    logsection('Staging Info-Zip')
    unpack(INSTALL_UNZ, INFOZIP_OUT_PATH)
    unpack(INSTALL_ZIP, INFOZIP_OUT_PATH)

    # Copy unzip.exe and zip.exe to the main bin directory to make our PATH bit more tidy
    copy(path(INFOZIP_OUT_PATH, 'unzip.exe'), BIN_PATH)
    copy(path(INFOZIP_OUT_PATH,   'zip.exe'), BIN_PATH)

#----------------------------------------------------------------------------

if not MSYS_EXTRA:
    if FETCH_TOOLS:
        logsubhead('Trying to fetch latest UPX')
        INSTALL_UPX = github('upx', 'upx',
            lambda asset: 'win64' in asset['name'].lower()
        ) or INSTALL_UPX

    logsection('Staging UPX')
    copy(path(BIN_PATH, unpack(INSTALL_UPX, BIN_PATH), 'upx.exe'), BIN_PATH)

#----------------------------------------------------------------------------

logsection('Staging nsinstall')
copy(path(CONTENT_PATH, 'nsinstall.exe'), BIN_PATH)

#----------------------------------------------------------------------------

if FETCH_TOOLS:
    logsubhead('Trying to fetch an latest vswhere')
    VSWHERE = github('microsoft', 'vswhere',
        lambda asset: ext(asset['name']) == 'exe'
    ) or VSWHERE

logsection('Staging vswhere')
copy(VSWHERE, BIN_PATH)

#----------------------------------------------------------------------------

logsection('Staging watchman')
unpack(INSTALL_WATCH, BIN_PATH)

# copy license
copy(path(CONTENT_PATH, 'watchman-LICENSE'), BIN_PATH)

#----------------------------------------------------------------------------

logsection('Locating MSYS2 components and dependencies')

# these pacakges may require restarting the MSYS shell in regular cases
# before continuing, so we install them first
CORE_PKGS = ([
    'msys2-runtime',
    'bash',
]) + ([
    'pacman',
    'pacman-mirrors'
] if MSYS_PACMAN else [])

REQD_PKGS = ([
    'bash-completion',
    'diffutils',
    'ed',
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
]) + ([
    # skip these when MSYS_PACMAN == True,
    # as they were pulled as dependencies of pacman in PKGS_CORE
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
] if not MSYS_PACMAN else [])

# extra packages available in msys base repo
EXTRA_PKGS = ([
#   'emacs',    # available, but we use our own no-deps version
    'zip',
    'unzip',
    'upx',      # installs ucl compression algo as a separate package
    # kdiff3 ?
])

# optinally useful: developer libs in msys base repo
DEVEL_PKGS = ([
    'pkgconf',  # install pkg-config for mach --with-system-LIBX
    'icu-devel',
    'libevent-devel',
    'libffi-devel',
    'zlib-devel',
    # nspr ?
    # libpng ?
    # icu4x ?
])

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
MSYS2_ENV['PATH'] = os.pathsep.join([
    path(REF_PATH, 'usr', 'bin'),
    MSYS2_ENV['PATH']])

#----------------------------------------------------------------------------
# function to call pacman in the staging root
# using a wrapper to execute the cmd / capture the output

def pacman(pkgs:list[str]=[], env:dict[str,str]=MSYS2_ENV,
           op:list[str]=['--sync', '--refresh', '--noconfirm'],
           wrap_call:Callable[[Cmd],T]=command) -> T:
    wrap_call([REF_PACMAN, '--root', MSYS2_PATH, *op, *pkgs], env=env)

#----------------------------------------------------------------------------
# Install msys2-runtime (and pacman if opted) first
# so that post-install scripts run successfully

pkglabel=' + '.join(
    filter(nuls, ['core', MSYS_PACMAN and 'pacman']))

logsubhead(f'Syncing {pkglabel} MSYS2 packages')
pacman(CORE_PKGS)

pkglabel=' + '.join(
    filter(nuls, ['required', MSYS_EXTRA and 'extra', MSYS_DEVEL and 'dev']))

logsubhead(f'Syncing {pkglabel} MSYS2 packages')
pacman((REQD_PKGS) +
       (EXTRA_PKGS if MSYS_EXTRA else []) +
       (DEVEL_PKGS if MSYS_DEVEL else []))

#----------------------------------------------------------------------------

if FETCH_SOURCES:
    logsubhead('Downloading MSYS2 package sources')
    OUT_SRC_PATH = path(OUT_PATH, 'sources')
    mkdirs(OUT_SRC_PATH)
    command([REF_CURL, '-sLS#', '--remote-name-all'] + (
        f'https://repo.msys2.org/msys/sources/{name}-{version}.src.tar.gz'
        for name, version in
            (line.split(' ') for line in
                pacman(op=['--query'], wrap_call=output).splitlines()))
    , cwd=OUT_SRC_PATH)

#----------------------------------------------------------------------------

logsection('Staging emacs')
unpack(INSTALL_EMACS, path(MSYS2_PATH, 'usr'), 'xztar')

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

def collect_dlls(filepath:Path):
    if (ext(filepath) != 'dll'): return

    # "msys-perl5_32.dll" is in both "/usr/bin/" and "/usr/lib/perl5/...".
    # Since "editbin /rebase" fails if it's provided equivalent dlls, let's
    # ensure no two dlls with the same name are added.
    if (filepath in msys_dlls): return

    os.chmod(filepath, stat.S_IWRITE)
    msys_dlls[basename(filepath)] = os.path.relpath(filepath, MSYS2_PATH)

withfilesin(MSYS2_PATH, do=collect_dlls)

#----------------------------------------------------------------------------

logsubhead('Rebasing collected DLL-s')

tools_version=getcontents(path(MSVC_PATH, 'VC', 'Auxiliary', 'Build',
                               'Microsoft.VCToolsVersion.default.txt'))
EDITBIN=path(MSVC_PATH, 'VC', 'Tools', 'MSVC',
             tools_version, 'bin', 'HostX64', 'x64', 'editbin.exe')

def dllrebase(*file_list:Path, base:str, cwd:Path=None):
    run([EDITBIN, '/NOLOGO',
         f'/REBASE:BASE={base}', '/DYNAMICBASE:NO', *file_list
    ], cwd=cwd, check=True)

# rebase collected DLL-s
dllrebase(*(msys_dlls.values()), base='0x60000000,DOWN', cwd=MSYS2_PATH)

# msys-2.0.dll is special and needs to be rebased independent of the rest
dllrebase(path(MSYS2_UBIN, 'msys-2.0.dll'), base='0x60100000')

logsuccess(f'rebased {len(msys_dlls)+1} DLL-s', 'DONE')

#----------------------------------------------------------------------------
# Embed some fiendly manifests to make UAC happy.

msys_exes={}

logsection('Embedding UAC-friendly manifests in executable files')
def embed_manifest(filepath:Path):
    if ext(filepath) != 'exe': return
    run([path(SDK_PATH, 'mt.exe'), '-nologo',
            '-manifest', path(SRC_PATH, 'noprivs.manifest'),
           f'-outputresource:{filepath};#1'
    ], check=True)
    msys_exes[basename(filepath)] = os.path.relpath(filepath, MSYS2_PATH)

withfilesin(MSYS2_PATH, do=embed_manifest)
logsuccess(f'embedded {len(msys_exes)} manifests', 'DONE')

#----------------------------------------------------------------------------

logsection('Configure staged MSYS')

# db_home:  Set "~" to point to "%USERPROFILE%"
# db_gecos: Fills out gecos information
#           (such as the user's full name) from AD/SAM.
putcontents(path(MSYS2_ETC, 'nsswitch.conf'), dedent(
    """
    db_home: windows
    db_gecos: windows
    """
))

# vi/vim wrapper
putcontents(path(MSYS2_UBIN, 'vi'), dedent(
    """
    #!/bin/sh
    exec vim "$@"
    """
))

if not MSYS_PACMAN:
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
copy(path(CONTENT_PATH, 'msys-config', 'ssh_config'),
     path(MSYS2_ETC, 'ssh'))
copy(path(CONTENT_PATH, 'msys-config', 'profile-mozilla.sh'),
     path(MSYS2_ETC, 'profile.d'))

#----------------------------------------------------------------------------

logsubhead('Installing bash-completion helpers')
COMPLETIONS = path(MSYS2_USR, 'share', 'bash-completion', 'completions')

download('https://www.mercurial-scm.org/repo/hg/raw-file/tip/contrib/bash_completion',
         path(COMPLETIONS, 'hg'))

download('https://raw.githubusercontent.com/git/git/master/contrib/completion/git-completion.bash',
         path(COMPLETIONS, 'git'))

# FIXME: umm, this one is way to laggy to use
# tested on a SSD, with hg clone mozilla-unified, with a i7-9750H cpu
# download('https://hg.mozilla.org/mozilla-unified/raw-file/tip/python/mach/bash-completion.sh',
#           path(COMPLETIONS, 'mach'))
# and the script generated by 'mach mach-autocomplete bash' seems to be source root specific :/

# FIXME: not needed (?) (as the preferred way of running pip should be
# with 'mach python -m pip' in a source root)
putcontents(path(COMPLETIONS, 'pip'),
            output([path(PY3_PATH, 'python3.exe'), '-m', 'pip', 'completion', '--bash']))
shebang_fix(path(COMPLETIONS, 'pip'))

# FIXME: maybe 'pip competion --bash' and 'rustup complete bash' etc can go into post ?

#============================================================================
# ALL STAGED, LETS PACKAGEIT!

logsection('Packaging the installer')
if FETCH_TOOLS:
    logsubhead('Fetching latest NSIS')
    INSTALL_NSIS = winget('NSIS', 'NSIS',
        lambda installer: installer['Architecture'] == 'x86',
        lambda url: sourceforge_url(url).replace('-setup.exe', '.zip')
    ) or INSTALL_NSIS

logsubhead('Unpacking NSIS tools')
NSISOUT_PATH = unpack(INSTALL_NSIS, OUT_PATH)

#----------------------------------------------------------------------------

logsubhead('Prepping installer scripts')

INSTALLER_NSI = 'installit.nsi'
LICENSE_FILE  = 'license.rtf'

copy(path(NSISSRC_PATH, 'setup.ico'),        OUT_PATH)
copy(path(NSISSRC_PATH, 'helpers.nsi'),      OUT_PATH)
copy(path(NSISSRC_PATH, 'mozillabuild.bmp'), OUT_PATH)

def replaceversion(text:Text) -> Text:
    return text.replace('@VERSION@', VERSION)

# replace the version placeholder in the license file
# also make a copy in the installation folder
copy(path(NSISSRC_PATH, LICENSE_FILE), OUT_PATH)
modcontents(path(OUT_PATH, LICENSE_FILE), replaceversion)
copy(path(OUT_PATH, LICENSE_FILE), MOZ_PATH)

# replace the version placeholder in the install script
copy(path(NSISSRC_PATH, INSTALLER_NSI), OUT_PATH)
modcontents(path(OUT_PATH, INSTALLER_NSI), replaceversion)

#----------------------------------------------------------------------------

logsubhead('Packaging with NSIS...')
command([path(OUT_PATH, NSISOUT_PATH, 'makensis.exe'),
         '/NOCD', INSTALLER_NSI], cwd=OUT_PATH)

logsuccess(f'MozillaBuild v{VERSION} installer package ready')

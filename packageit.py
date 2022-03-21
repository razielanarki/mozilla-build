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

import libpackageit.config as config

config.PWD = dirname(abspath(__file__))

exit

from re import sub as replace
from subprocess import check_call

from libpackageit import *

#============================================================================
# USAGE


Config().VSWHERE=path(PWD, 'sources', 'vswhere.exe')

args = (Parser()
    ).arg(
        '-m', '--msys2-ref-path', default=path('C:\\msys64'), type=str,
        dest='REF_PATH',
        help='Path to reference MSYS2 installation (containing curl and pacman)',
    ).arg(
        '-s', '--sources-path', default=path(PWD, 'sources'), type=str,
        dest='SRC_PATH',
        help='Path to source directory for bundled tools and configs',
    ).arg(
        '-o', '--staging-path', default=path(PWD, 'stage'), type=str,
        dest='OUT_PATH',
        help='Path to desired staging directory'
    ).arg(
        '-v', '--msvc-path', default=vswhere('installationPath'), type=str,
        dest='MSVC_PATH',
        help='Path to Visual Studio installation',
    ).arg(
        '-w', '--win10-sdk-path', default=sdkpath(), type=str,
        dest='WSDK_PATH',
        help='Path to Windows 10 SDK installation folder'
    ).arg(
        '-f', '--fetch-sources', default=False, action='store_true',
        dest='FETCH_SRCS',
        help=f'Download MSYS2 packags sources to "{path("OUT_PATH", "src")}"',
    ).arg(
        '-u', '--fetch-tools', nargs='?', default=False, choices=['with-cache', 'without-cache'],
        dest='FETCH_TOOLS',
        help=f'Download latest tool updates to "{path("PWD", "temp")}", and bundle them.',
    ).arg(
        '-x', '--msys-extra', default=False, action='store_true',
        dest='MSYS_EXTRA',
        help='Bundle pacman, pkg-config, info-zip, emacs and upx from the MSYS2 base repo',
    ).arg(
        '-d', '--msys-devel', default=False, action='store_true',
        dest='MSYS_DEVEL',
        help='Bundle libicu4c-devel, libffi-devel, libevent-devel and zlib-devel from MSYS2',
    ).parse()

print(Config())

SRC_PATH   = args.source_path
REF_PATH   = args.msys2_ref_path
OUT_PATH   = args.staging_path
MSVC_PATH  = args.msvc_path
WSDK_PATH  = args.win10_sdk_path
FETCH_SRCS = args.fetch_sources
FETCH_TOOL = args.fetch_utils
MSYS_EXTRA = args.msys_extra
MSYS_DEVEL = args.msys_devel

#============================================================================
# SUPPLEMENTARY CONFIG

# refrerenced binaries from MSYS
REF_PACMAN = path(REF_PATH, 'usr', 'bin', 'pacman.exe')
REF_CURL   = path(REF_PATH, 'usr', 'bin', 'curl.exe')

# installers, content, nsis cripts
INSTALL_PATH = path(SRC_PATH, 'installers')
CONTENT_PATH = path(SRC_PATH, 'content')
NSISSRC_PATH = path(SRC_PATH, 'nsis')

# download cache
TMP_PATH = path(PWD, 'temp')

# workdir and important subdirs
MOZ_PATH = path(OUT_PATH, 'mozilla-build')
BIN_PATH = path(MOZ_PATH, 'bin')
PY3_PATH = path(MOZ_PATH, 'python3')
PYSCRPTS = path(PY3_PATH, 'Scripts')

# utilites
VSWHERE  = path(SRC_PATH, 'vswhere.exe')
YML2JSON = path(SRC_PATH, 'y2j.exe')
UN7IP    = path(BIN_PATH, '7z.exe' )

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
# PRINT VERSION + PARSED ARGS AS HEADER

VERSION = getfile(path(PWD, 'VERSION'))

logopts(
    f'{C(BOLD, BLUE)}MozillaBuild PACKAGEIT {fchrs(":")} {C(BOLD, MAGENTA)}{VERSION}',
    [
        ('Source location',                SRC_PATH),
        ('Reference (host) MSYS2 install', REF_PATH),
        ('Staging folder',                 OUT_PATH),
        ('MSVC install path',              MSVC_PATH),
        ('Latest Windows SDK path',        WSDK_PATH),
        ('Download MSYS2 package sources', FETCH_SRCS),
        ('Download latest tool updates',   FETCH_TOOL),
        ('Bundle extras with MSYS2',       MSYS_EXTRA),
        ('Bundle devel libs with MSYS2',   MSYS_DEVEL),
    ]
)
exit
#============================================================================
# PACKINGTIME!

#----------------------------------------------------------------------------
# assert for pacman and curl in referenve MSYS2

logsection('Check reference MSYS2')
for filepath in [REF_PACMAN, REF_CURL]:
    assert isfile(filepath), f'Reference MSYS2 installation is invalid:\n\t"{filepath}" missing'

#----------------------------------------------------------------------------
# clear leftovers form previous run

if (pathexists(OUT_PATH)):
    logsubhead('Removing the previous staging directory')
    rmdir(OUT_PATH)

if (FETCH_TOOL == 'without-cache' and pathexists(TMP_PATH)):
    logsubhead('Removing the previous temp directory')
    rmdir(TMP_PATH)

#----------------------------------------------------------------------------

logsubhead('Creating the working dirs')
mkdirs(TMP_PATH, OUT_PATH, MOZ_PATH, BIN_PATH)

#----------------------------------------------------------------------------

if FETCH_TOOL:
    logsubhead('Trying to fetch latest 7-Zip')
    INSTALL_7ZIP = winget('7zip', '7zip', # get the latest x64 MSI
        lambda installer: installer['Architecture'] == 'x64' and installer['InstallerType'] == 'wix'
    ) or INSTALL_7ZIP

logsection('Staging 7-Zip')
mkdirs(path(OUT_PATH, '7zip'))

# Create an administrative install point and copy the files to stage rather
# than using a silent install to avoid installing the shell extension on the host machine.
call(['msiexec.exe', '/q', '/a', INSTALL_7ZIP, f'TARGETDIR={path(OUT_PATH, "7zip")}'])

copydir(path(OUT_PATH, '7zip', 'Files', '7-Zip'), path(BIN_PATH, '7zip'))
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
    '--ignore-installed', '--upgrade', '--no-warn-script-location'
] + PIP_PACKAGES)

#----------------------------------------------------------------------------
# Find any occurrences of hardcoded interpreter paths in the Scripts directory and change them
# to a generic python.exe instead. Awful, but distutils hardcodes the interpreter path in the
# scripts, which breaks because it uses the path on the machine we built this package on, not
# the machine it was installed on. And unfortunately, pip doesn't have a way to pass down the
# --executable flag to override this behavior.
# See http://docs.python.org/distutils/setupscript.html#installing-scripts
# Do the shebang fix on Python3 too.
# Need to special-case c:\python3\python.exe too, due to the
# aforementioned packaging issues above.

logsubhead('distutils shebang fix')

FIX_BANGS = [
    'C:\\python3\\python.exe',
    path(PY3_PATH, "python3.exe")
]

def shebang_fix(dirpath:str, filename:str):
    if not hasext(filename, 'exe'):
        return

    processfile(
        path(dirpath, filename),
        lambda contents: replace(f'(?i){"|".join(FIX_BANGS)}', 'python3.exe', contents)
    )

recursedir(PYSCRPTS, shebang_fix)

#----------------------------------------------------------------------------
# Extract KDiff3 to the stage directory. The KDiff3 installer doesn't support any sort of
# silent installation, so we use a ready-to-extract 7-Zip archive instead.

logsection('Staging KDiff3')
un7ip(INSTALL_KDIFF, path(MOZ_PATH, 'kdiff3'))

# note: winget-pkgs has "JoachimEibl/Kiff3":v0.9.98 (points to sourceforge),
# and a newer/updated "KDE/Kdiff" form from the original author (points to github)
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
    copy(path(INFOZIPOUT_PATH,   'zip.exe'), BIN_PATH)

#----------------------------------------------------------------------------

if not MSYS_EXTRA:
    if FETCH_TOOL:
        logsubhead('Fetching latest UPX')
        INSTALL_UPX = github ('upx', 'upx',
            lambda asset: 'win64' in asset['name'].lower()
        ) or INSTALL_UPX

    logsection('Staging UPX')
    copy(path(BIN_PATH, unzip(INSTALL_UPX, BIN_PATH), 'upx.exe'), BIN_PATH )

#----------------------------------------------------------------------------

logsection('Staging nsinstall')
copy(path(CONTENT_PATH, 'nsinstall.exe'), BIN_PATH)

#----------------------------------------------------------------------------

if FETCH_TOOL:
    logsubhead('Fetching latest vswhere')
    VSWHERE = github('microsoft', 'vswhere',
        lambda asset: hasext(asset['name'], 'exe')
    ) or VSWHERE

logsection('Staging vswhere')
copy(VSWHERE, BIN_PATH)

#----------------------------------------------------------------------------

logsection('Staging watchman')
unzip(INSTALL_WATCH, BIN_PATH)
copy(path(CONTENT_PATH, 'watchman-LICENSE'), BIN_PATH)

#----------------------------------------------------------------------------

logsection('Locating MSYS2 components and dependencies')

CORE_PKGS = [
    'msys2-runtime',
    'bash'
] + ([
    'pacman',
    'pacman-mirrors'
] if MSYS_EXTRA else [])

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
] + ([ # these are installed with pacman if MSYS_EXTRA == True
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
    # kdiff3 is not in msys2 repo  (yet)
]

# could be useful: developer libs in msys base repo
DEVEL_PKGS = [
    'icu-devel',
    'libevent-devel',
    'libffi-devel',
    'zlib-devel',
    # nspr   is not in base msys2 repo (yet)
    # libpng is not in base msys2 repo  (yet)
    # icu4x  is not in base msys2 repo  (yet)
]

#----------------------------------------------------------------------------
# Extract MSYS2 packages to the stage directory

logsection('Syncing MSYS2 packages')

MSYS2_PATH = path(MOZ_PATH, 'msys2')
mkdirs(path(MSYS2_PATH, 'tmp'),
       path(MSYS2_PATH, 'var', 'lib', 'pacman'),
       path(MSYS2_PATH, 'var', 'log'))

MSYS2_ETC  = path(MSYS2_PATH, 'etc')
MSYS2_USR  = path(MSYS2_PATH, 'usr')
MSYS2_UBIN = path(MSYS2_USR,  'bin')

MSYS2_ENV = envcopy()
MSYS2_ENV['PATH'] = pathenv(path(REF_PATH, 'usr', 'bin'), MSYS2_ENV['PATH'])

#----------------------------------------------------------------------------
# function to call pacman in the staging root
# using a wrapper to execute the cmd / capture the output

def pacman(args:Cmd=[], cmd:str='Syc', env:Env=MSYS2_ENV, wrap_call:Any=command) -> ...:
    return wrap_call([REF_PACMAN, f'-{cmd}', '--noconfirm', '--verbose', '--root', MSYS2_PATH] + args, env=env)

#----------------------------------------------------------------------------
# Install core packages first
# so that post-install scripts can run successfully

logsubhead('Syncing core MSYS2 packages')
pacman(CORE_PKGS)

pkgs=" + ".join(
    (['required']) +
    (['extra'] if MSYS_EXTRA else []) +
    (['devel'] if MSYS_DEVEL else [])
)
logsubhead(f'Syncing {pkgs} MSYS2 packages')
pacman(
    (REQD_PKGS) +
    (EXTRA_PKGS if MSYS_EXTRA else []) +
    (DEVEL_PKGS if MSYS_DEVEL else [])
)

#----------------------------------------------------------------------------

if FETCH_SRCS:
    logsubhead('Downloading MSYS2 package sources')
    OUT_SRC_PATH = path(OUT_PATH, 'src'); mkdirs(OUT_SRC_PATH)
    command([REF_CURL, '-sLS#', '--remote-name-all'] + ([
        f'https://repo.msys2.org/msys/sources/{name}-{version}.src.tar.gz'
        for name, version in (line.split(' ') for line in pacman(cmd='Q', wrap_call=capture).splitlines())
    ]), cwd=OUT_SRC_PATH)

#----------------------------------------------------------------------------

if not MSYS_EXTRA:
    # Extract emacs to the stage directory
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

msys_dlls:dict[str, str] = {}

def collect_dlls(dirpath:str, filename:str):
    if not hasext(filename, 'dll'):
        return

    filepath = path(dirpath, filename)
    chmod(filepath, 0o755)

    # "msys-perl5_32.dll" is in both "/usr/bin/" and "/usr/lib/perl5/...".
    # Since "editbin /rebase" fails if it's provided equivalent dlls, let's
    # ensure no two dlls with the same name are added.
    if filename in msys_dlls:
        return

    msys_dlls[filename] = relpath(filepath, MSYS2_PATH)

recursedir(MSYS2_PATH, collect_dlls)

#----------------------------------------------------------------------------

logsubhead('Rebasing collected DLL-s')

tools_version=getfile(path(MSVC_PATH, 'VC', 'Auxiliary', 'Build', 'Microsoft.VCToolsVersion.default.txt'))
EDITBIN=path(MSVC_PATH, 'VC', 'Tools', 'MSVC', tools_version, 'bin', 'HostX64', 'x64', 'editbin.exe')

def editbin(file_list:list[str], base:str, cwd:str=...):
    check_call([EDITBIN, '/NOLOGO', '/REBASE:BASE=' + base, '/DYNAMICBASE:NO'] + file_list, cwd=cwd)

# rebase collected DLLS
editbin(list(msys_dlls.values()), '0x60000000,DOWN', MSYS2_PATH)

# msys-2.0.dll is special and needs to be rebased independent of the rest
editbin([path(MSYS2_UBIN, 'msys-2.0.dll')], '0x60100000')

#----------------------------------------------------------------------------
# Embed some fiendly manifests to make UAC happy.

logsection('Embedding UAC-friendly manifests in executable files')
def embed_mainfest(dirpath:str, filename:str):
    if not hasext(filename, 'exe'):
        return

    check_call([path(WSDK_PATH, 'mt.exe'), '-nologo',
        '-manifest', path(SRC_PATH, 'noprivs.manifest'),
        f'-outputresource:{path(dirpath, filename)};#1'
    ])

recursedir(MSYS2_PATH, embed_mainfest)

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
    try: rm(path(MSYS2_ETC, 'post-install', '07-pacman-key.post'))
    except: pass

# We didn't install the xmlcatalog binary.
try: rm(path(MSYS2_ETC, 'post-install', '08-xml-catalog.post'))
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
curl('https://raw.githubusercontent.com/git/git/master/contrib/completion/git-completion.bash', COMPLETIONS, 'git')

## FIXME: umm, this one is wwaayy ssllooww to respond :/
## -> tested on a hg clone of mozilla-unified, with an i7-9750H (6x2 cores) + ON A SSD
# curl('https://hg.mozilla.org/mozilla-unified/raw-file/tip/python/mach/bash-completion.sh', COMPLETIONS, 'mach')
## and the script generated by 'mach mach-autocomplete bash' seems to be source root specific :/

## FIXME: not needed (?) (as the preferred way of running pip should be with 'mach python -m pip' in a source root)
# saveoutput([path(PY3_PATH, 'python3.exe'), '-m', 'pip', 'completion', '--bash'], path(COMPLETIONS, 'pip'))
# shebang_fix(dirpath=COMPLETIONS, filename='pip')

## FIXME: maybe 'pip competion --bash' and 'rustup complete bash' etc can go into post ?

#============================================================================
# ALL STAGED, LETS PACKAGEIT!

logsection('Packaging the installer')
if FETCH_TOOL:
    logsubhead('Fetching latest NSIS')
    INSTALL_NSIS = winget('NSIS', 'NSIS',
        lambda installer: installer['Architecture'] == 'x86',
        lambda url: sanitizeforge(url).replace('-setup.exe', '.zip')
    ) or INSTALL_NSIS

logsubhead('Unzipping NSIS')
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
processfile(path(OUT_PATH, LICENSE_FILE), replaceversion)
copy(path(OUT_PATH, LICENSE_FILE), MOZ_PATH)

copy(path(NSISSRC_PATH, INSTALLER_NSI), OUT_PATH)
processfile(path(OUT_PATH, INSTALLER_NSI), replaceversion)

#----------------------------------------------------------------------------

logsubhead('Packaging with NSIS...')
command([path(OUT_PATH, NSISOUT_PATH, 'makensis.exe'), '/NOCD', INSTALLER_NSI], cwd=OUT_PATH)

#============================================================================

logsection(f'PACKAGING MozillaBuild v{VERSION} {C(DIM, GREEN, YELLOW+BGR, INV)} DONE! {C()}')

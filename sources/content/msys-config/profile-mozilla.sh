#!/bin/sh
#shellcheck shell=bash disable=SC1090,2009

export EDITOR="nano.exe"
# note: scm editor config, and encoding moved to mercurial.ini
# to allow the user to everride them in their own gitconfig/mercurial.ini

# Make prompt shorter than default MSYS2 prompt: don't show "$MSYSTEM"
# (which would be "MINGW64", "MSYS", etc) since MozillaBuild always executes
# with "MSYSTEM=MSYS"
export PS1="\[\e]0;MozillaBuild:\w\a\]\n\[\e[32m\]\u@\h \[\e[33m\]\w\[\e[0m\]\n\$ "

# emulate old msys way of finding executables in the current path
# so users can type "mach build" instead of "./mach build"
# (as in MozillaBuild 3.4)
PATH=".:$PATH"

# Unbind "ctrl-v" from the "lnext" special character so that it can
# instead be used to paste.
stty lnext undef

if [ -n "$MOZILLABUILD" ]; then
  # $MOZILLABUILD should always be set by start-shell.bat.
  echo "MozillaBuild Install Directory: ${MOZILLABUILD}"
  mozillabuild_unix=$(cygpath -u "$MOZILLABUILD")
  mozillabuild_unix=${mozillabuild_unix%/} # Remove trailing slash
  PATH="$mozillabuild_unix/bin:$mozillabuild_unix/kdiff3:$mozillabuild_unix/python3:$mozillabuild_unix/python3/Scripts:$PATH"

  # Pip-installed mercurial puts two files in the Python Scripts directory: "hg" (a text, unix-y file), and "hg.exe".
  # Use hg.exe to avoid https://bz.mercurial-scm.org/show_bug.cgi?id=6614
  alias hg=hg.exe
fi

if [ -z "$EXTERNAL_TO_MOZILLABUILD_SSH_DIR" ]; then
  # This script loads ssh-agent and shares the instance across multiple instances
  # of rxvt.
  #
  # Written and released under GPL by Joseph Reagle, found here:
  # http://www.cygwin.com/ml/cygwin/2001-06/msg00537.html
  #
  # This program is free software: you can redistribute it and/or modify
  # it under the terms of the GNU General Public License as published by
  # the Free Software Foundation, either version 3 of the License, or
  # (at your option) any later version.
  #
  # This program is distributed in the hope that it will be useful,
  # but WITHOUT ANY WARRANTY; without even the implied warranty of
  # MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
  # GNU General Public License for more details.
  #
  # You should have received a copy of the GNU General Public License
  # along with this program.  If not, see <http://www.gnu.org/licenses/>.
  SSH_ENV="$HOME/.ssh/environment"

  start_agent() {
    ssh-agent | sed 's/^echo/#echo/' > "${SSH_ENV}"
    chmod 600 "${SSH_ENV}"
    . "${SSH_ENV}" > /dev/null
    ssh-add;
  }

  if [ -d "$HOME/.ssh" ]; then
    if [ -f "${SSH_ENV}" ]; then
      . "${SSH_ENV}" > /dev/null
      ps -ef | grep "${SSH_AGENT_PID}" | grep "ssh-agent$" > /dev/null || {
        start_agent;
      }
    else
      start_agent;
    fi
  fi
else
  PATH="$(cygpath -u "$EXTERNAL_TO_MOZILLABUILD_SSH_DIR"):$PATH"
fi

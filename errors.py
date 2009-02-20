#    errors.py -- Error classes
#    Copyright (C) 2006 James Westby <jw+debian@jameswestby.net>
#
#    This file is part of bzr-builddeb.
#
#    bzr-builddeb is free software; you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation; either version 2 of the License, or
#    (at your option) any later version.
#
#    bzr-builddeb is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with bzr-builddeb; if not, write to the Free Software
#    Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301  USA
#

from bzrlib.errors import BzrError


class DebianError(BzrError):
    _fmt = "A Debian packaging error occurred: %(cause)s"

    def __init__(self, cause):
        BzrError.__init__(self, cause=cause)


class NoSourceDirError(BzrError):
    _fmt = ("There is no existing source directory to use. Use "
            "--export-only or --dont-purge to get one that can be used")


class BuildFailedError(BzrError):
    _fmt = "The build failed."


class UnparseableChangelog(BzrError):
    _fmt = "There was an error parsing the changelog: %(error)s"

    def __init__(self, error):
        BzrError.__init__(self, error=error)


class StopBuild(BzrError):
    _fmt = "Stopping the build: %(reason)s."

    def __init__(self, reason):
        BzrError.__init__(self, reason=reason)


class MissingChangelogError(BzrError):
    _fmt = 'Could not find changelog at %(locations)s.'

    def __init__(self, locations):
        BzrError.__init__(self, location=locations)


class AddChangelogError(BzrError):
    _fmt = 'Please add "%(changelog)s" to the branch using bzr add.'

    def __init__(self, changelog):
        BzrError.__init__(self, changelog=changelog)


class ImportError(BzrError):
    _fmt = "The files could not be imported: %(reason)s"

    def __init__(self, reason):
        BzrError.__init__(self, reason=reason)


class HookFailedError(BzrError):
    _fmt = 'The "%(hook_name)s" hook failed.'

    def __init__(self, hook_name):
        BzrError.__init__(self, hook_name=hook_name)


class OnlyImportSingleDsc(BzrError):
    _fmt = "You are only allowed to import one version in incremental mode."


class UnknownType(BzrError):
    _fmt = 'Cannot extract "%(path)s" from archive as it is an unknown type.'

    def __init__(self, path):
        BzrError.__init__(self, path=path)


class MissingChanges(BzrError):
    _fmt = "Could not find .changes file: %(changes)s."

    def __init__(self, changes):
        BzrError.__init__(self, changes=changes)


class UpstreamAlreadyImported(BzrError):
    _fmt = 'Upstream version "%(version)s" has already been imported.'

    def __init__(self, version):
        BzrError.__init__(self, version=str(version))


class UpstreamBranchAlreadyMerged(BzrError):
    _fmt = 'That revision of the upstream branch has already been merged.'


class AmbiguousPackageSpecification(BzrError):
    _fmt = ('You didn\'t specify a distribution with the package '
            'specification, and tags exists that state that the '
            'version that you specified has been uploaded to more '
            'than one distribution. Please specify which version '
            'you wish to refer to by by appending ":debian" or '
            '":ubuntu" to the revision specifier: %(specifier)s')

    def __init__(self, specifier):
        BzrError.__init__(self, specifier=specifier)


class UnknownVersion(BzrError):
    _fmt = ('No tag exists in this branch indicating that version '
            '"%(version)s" has been uploaded.')

    def __init__(self, version):
        BzrError.__init__(self, version=version)


class UnknownDistribution(BzrError):
    _fmt = "Unknown distribution: %(distribution)s."

    def __init__(self, distribution):
        BzrError.__init__(self, distribution=distribution)


class VersionNotSpecified(BzrError):
    _fmt = "You did not specify a package version."


class UnsupportedRepackFormat(BzrError):
    _fmt = ('Either the file extension of "%(location)s" indicates that '
            'it is a format unsupported for repacking or it is a '
            'remote directory.')

    def __init__(self, location):
        BzrError.__init__(self, location=location)


class PristineTarError(BzrError):
    _fmt = 'There was an error using pristine-tar: %(error)s.'

    def __init__(self, error):
        BzrError.__init__(self, error=error)

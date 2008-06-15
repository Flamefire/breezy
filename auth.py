# Copyright (C) 2005-2007 Jelmer Vernooij <jelmer@samba.org>
 
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

"""Authentication token retrieval."""

from bzrlib.config import AuthenticationConfig
from bzrlib.ui import ui_factory

from bzrlib.plugins.svn.ra import (get_username_prompt_provider, 
                                   get_simple_prompt_provider,
                                   get_ssl_server_trust_prompt_provider,
                                   get_ssl_client_cert_pw_prompt_provider)

import svn.core
from svn.core import (svn_auth_cred_username_t, 
                      svn_auth_cred_simple_t,
                      svn_auth_cred_ssl_client_cert_t,
                      svn_auth_cred_ssl_client_cert_pw_t,
                      svn_auth_cred_ssl_server_trust_t,
                      svn_auth_open)
import urlparse
import urllib

SSL_NOTYETVALID = 0x00000001
SSL_EXPIRED     = 0x00000002
SSL_CNMISMATCH  = 0x00000004
SSL_UNKNOWNCA   = 0x00000008
SSL_OTHER       = 0x40000000

class SubversionAuthenticationConfig(AuthenticationConfig):
    """Simple extended version of AuthenticationConfig that can provide 
    the information Subversion requires.
    """
    def __init__(self, scheme, host, port, path, file=None):
        super(SubversionAuthenticationConfig, self).__init__(file)
        self.scheme = scheme
        self.host = host
        self.port = port
        self.path = path
       
    def get_svn_username(self, realm, may_save, pool=None):
        """Look up a Subversion user name in the Bazaar authentication cache.

        :param realm: Authentication realm (optional)
        :param may_save: Whether or not the username should be saved.
        :param pool: Allocation pool, is ignored.
        :param default: Assumed username
        """
        username_cred = svn_auth_cred_username_t()
        username_cred.username = self.get_user(self.scheme, 
                host=self.host, path=self.path, 
                realm=realm)
        username_cred.may_save = False
        return username_cred

    def get_svn_simple(self, realm, username, may_save, pool):
        """Look up a Subversion user name+password combination in the Bazaar 
        authentication cache.

        :param realm: Authentication realm (optional)
        :param username: Username, if it is already known, or None.
        :param may_save: Whether or not the username should be saved.
        :param pool: Allocation pool, is ignored.
        """
        simple_cred = svn_auth_cred_simple_t()
        simple_cred.username = self.get_user(self.scheme, 
                host=self.host, path=self.path, realm=realm) or username
        simple_cred.password = self.get_password(self.scheme, host=self.host, 
            path=self.path, user=simple_cred.username, 
            realm=realm, prompt="%s %s password" % (realm, simple_cred.username))
        simple_cred.may_save = False
        return simple_cred

    def get_svn_ssl_server_trust(self, realm, failures, cert_info, may_save, 
                                     pool):
        """Return a Subversion auth provider that verifies SSL server trust.

        :param realm: Realm name (optional)
        :param failures: Failures to check for (bit field, SVN_AUTH_SSL_*)
        :param cert_info: Certificate information
        :param may_save: Whether this information may be stored.
        """
        ssl_server_trust = svn_auth_cred_ssl_server_trust_t()
        credentials = self.get_credentials(self.scheme, host=self.host)
        if (credentials is not None and 
            credentials.has_key("verify_certificates") and 
            credentials["verify_certificates"] == False):
            ssl_server_trust.accepted_failures = (
                    SSL_NOTYETVALID + 
                    SSL_EXPIRED +
                    SSL_CNMISMATCH +
                    SSL_UNKNOWNCA +
                    SSL_OTHER)
        else:
            ssl_server_trust.accepted_failures = 0
        ssl_server_trust.may_save = False
        return ssl_server_trust

    def get_svn_username_prompt_provider(self, retries):
        """Return a Subversion auth provider for retrieving the username, as 
        accepted by svn_auth_open().
        
        :param retries: Number of allowed retries.
        """
        return get_username_prompt_provider(self.get_svn_username, 
                                                     retries)

    def get_svn_simple_prompt_provider(self, retries):
        """Return a Subversion auth provider for retrieving a 
        username+password combination, as accepted by svn_auth_open().
        
        :param retries: Number of allowed retries.
        """
        return get_simple_prompt_provider(self.get_svn_simple, retries)

    def get_svn_ssl_server_trust_prompt_provider(self):
        """Return a Subversion auth provider for checking 
        whether a SSL server is trusted."""
        return get_ssl_server_trust_prompt_provider(self.get_svn_ssl_server_trust)

    def get_svn_auth_providers(self):
        """Return a list of auth providers for this authentication file.
        """
        return [self.get_svn_username_prompt_provider(1),
                self.get_svn_simple_prompt_provider(1),
                self.get_svn_ssl_server_trust_prompt_provider()]

def get_ssl_client_cert_pw(realm, may_save, pool):
    """Simple SSL client certificate password prompter.

    :param realm: Realm, optional.
    :param may_save: Whether the password can be cached.
    """
    ssl_cred_pw = svn_auth_cred_ssl_client_cert_pw_t()
    ssl_cred_pw.password = ui_factory.get_password(
            "Please enter password for client certificate[realm=%s]" % realm)
    ssl_cred_pw.may_save = False
    return ssl_cred_pw


def get_ssl_client_cert_pw_provider(tries):
    return get_ssl_client_cert_pw_prompt_provider(
                get_ssl_client_cert_pw, tries)


def get_stock_svn_providers():
    providers = [svn.client.get_simple_provider(),
            svn.client.get_username_provider(),
            svn.client.get_ssl_client_cert_file_provider(),
            svn.client.get_ssl_client_cert_pw_file_provider(),
            svn.client.get_ssl_server_trust_file_provider(),
            ]

    if hasattr(svn.client, 'get_windows_simple_provider'):
        providers.append(svn.client.get_windows_simple_provider())

    if hasattr(svn.client, 'get_keychain_simple_provider'):
        providers.append(svn.client.get_keychain_simple_provider())

    if hasattr(svn.client, 'get_windows_ssl_server_trust_provider'):
        providers.append(svn.client.get_windows_ssl_server_trust_provider())

    return providers


def create_auth_baton(url):
    """Create an authentication baton for the specified URL."""
    assert isinstance(url, str)
    (scheme, netloc, path, _, _) = urlparse.urlsplit(url)
    (creds, host) = urllib.splituser(netloc)
    (host, port) = urllib.splitport(host)

    auth_config = SubversionAuthenticationConfig(scheme, host, port, path)

    # Specify Subversion providers first, because they use file data
    # rather than prompting the user.
    providers = get_stock_svn_providers()

    if svn.core.SVN_VER_MAJOR == 1 and svn.core.SVN_VER_MINOR >= 5:
        providers += auth_config.get_svn_auth_providers()
        providers += [get_ssl_client_cert_pw_provider(1)]

    auth_baton = svn.core.svn_auth_open(providers)
    if creds is not None:
        (auth_baton.user, auth_baton.password) = urllib.splitpasswd(creds)
        if auth_baton.user is not None:
            svn.core.svn_auth_set_parameter(auth_baton, 
                svn.core.SVN_AUTH_PARAM_DEFAULT_USERNAME, auth_baton.user)
        if auth_baton.password is not None:
            svn.core.svn_auth_set_parameter(auth_baton, 
                svn.core.SVN_AUTH_PARAM_DEFAULT_PASSWORD, auth_baton.password)
    return auth_baton

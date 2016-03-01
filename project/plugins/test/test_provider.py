from __future__ import absolute_import

import os

import pytest

from project.internal.test.tmpfile_utils import with_directory_contents
from project.internal.crypto import encrypt_string
from project.local_state_file import LocalStateFile, LOCAL_STATE_DIRECTORY, LOCAL_STATE_FILENAME
from project.plugins.provider import Provider, ProvideContext, EnvVarProvider, ProviderConfigContext
from project.plugins.registry import PluginRegistry
from project.plugins.requirement import EnvVarRequirement
from project.project import Project
from project.project_file import ProjectFile, PROJECT_FILENAME


def test_find_providers_by_env_var():
    registry = PluginRegistry()
    found = registry.find_providers_by_env_var(requirement=None, env_var="FOO")
    assert 1 == len(found)
    assert isinstance(found[0], EnvVarProvider)
    assert "EnvVarProvider" == found[0].config_key


def test_find_provider_by_class_name():
    registry = PluginRegistry()
    found = registry.find_provider_by_class_name(class_name="ProjectScopedCondaEnvProvider")
    assert found is not None
    assert found.__class__.__name__ == "ProjectScopedCondaEnvProvider"


def test_find_provider_by_class_name_not_found():
    registry = PluginRegistry()
    found = registry.find_provider_by_class_name(class_name="NotAThing")
    assert found is None


def test_provider_default_method_implementations():
    class UselessProvider(Provider):
        @property
        def title(self):
            return ""

        def read_config(self, context):
            return dict()

        def provide(self, requirement, context):
            pass

    provider = UselessProvider()
    # this method is supposed to do nothing by default (ignore
    # unknown names, in particular)
    provider.set_config_values_as_strings(context=None, values=dict())
    # this is supposed to return None by default
    provider.config_html(context=None, status=None) is None


def _load_env_var_requirement(dirname, env_var):
    project = Project(dirname)
    for requirement in project.requirements:
        if isinstance(requirement, EnvVarRequirement) and requirement.env_var == env_var:
            return requirement
    raise RuntimeError("No requirement for %s was in the project file, only %r" % (env_var, project.requirements))


def test_env_var_provider_with_no_value():
    def check_env_var_provider(dirname):
        provider = EnvVarProvider()
        requirement = _load_env_var_requirement(dirname, "FOO")
        local_state_file = LocalStateFile.load_for_directory(dirname)
        config_context = ProviderConfigContext(dict(), local_state_file, requirement)
        config = provider.read_config(config_context)
        assert dict() == config
        context = ProvideContext(environ=dict(), local_state_file=local_state_file, config=config)

        provider.provide(requirement, context=context)
        assert 'FOO' not in context.environ

    with_directory_contents({PROJECT_FILENAME: """
runtime:
  - FOO
"""}, check_env_var_provider)


def test_env_var_provider_with_default_value_in_project_file():
    def check_env_var_provider(dirname):
        provider = EnvVarProvider()
        requirement = _load_env_var_requirement(dirname, "FOO")
        assert dict(default='from_default') == requirement.options
        local_state_file = LocalStateFile.load_for_directory(dirname)
        config_context = ProviderConfigContext(dict(), local_state_file, requirement)
        config = provider.read_config(config_context)
        context = ProvideContext(environ=dict(), local_state_file=local_state_file, config=config)
        provider.provide(requirement, context=context)
        assert 'FOO' in context.environ
        assert 'from_default' == context.environ['FOO']

    with_directory_contents(
        {PROJECT_FILENAME: """
runtime:
  FOO:
    default: from_default
"""}, check_env_var_provider)


def test_env_var_provider_with_encrypted_default_value_in_project_file():
    def check_env_var_provider(dirname):
        # Save a default value which is encrypted and the key is in var MASTER
        project_file = ProjectFile.load_for_directory(dirname)
        secret = "boo"
        encrypted = encrypt_string("from_default", secret)
        project_file.set_value(['runtime', 'FOO_SECRET'], dict(default=dict(key='MASTER', encrypted=encrypted)))
        project_file.save()

        provider = EnvVarProvider()
        requirement = _load_env_var_requirement(dirname, "FOO_SECRET")
        assert requirement.encrypted
        assert dict(default=dict(key='MASTER', encrypted=encrypted)) == requirement.options
        local_state_file = LocalStateFile.load_for_directory(dirname)
        config_context = ProviderConfigContext(dict(), local_state_file, requirement)
        assert ('ANACONDA_MASTER_PASSWORD', ) == provider.missing_env_vars_to_configure(
            requirement, config_context.environ, local_state_file)
        assert ('MASTER', ) == provider.missing_env_vars_to_provide(requirement, config_context.environ,
                                                                    local_state_file)
        config = provider.read_config(config_context)
        context = ProvideContext(environ=dict(MASTER=secret), local_state_file=local_state_file, config=config)
        provider.provide(requirement, context=context)
        assert 'FOO_SECRET' in context.environ
        assert 'from_default' == context.environ['FOO_SECRET']

    with_directory_contents(dict(), check_env_var_provider)


def test_env_var_provider_with_encrypted_default_value_in_project_file_for_non_encrypted_requirement():
    def check_env_var_provider(dirname):
        # Save a default value which is encrypted and the key is in var MASTER
        project_file = ProjectFile.load_for_directory(dirname)
        secret = "boo"
        encrypted = encrypt_string("from_default", secret)
        project_file.set_value(['runtime', 'FOO'], dict(default=dict(key='MASTER', encrypted=encrypted)))
        project_file.save()

        provider = EnvVarProvider()
        requirement = _load_env_var_requirement(dirname, "FOO")
        assert not requirement.encrypted  # this is the point of this test
        assert dict(default=dict(key='MASTER', encrypted=encrypted)) == requirement.options
        local_state_file = LocalStateFile.load_for_directory(dirname)
        config_context = ProviderConfigContext(dict(), local_state_file, requirement)
        config = provider.read_config(config_context)
        context = ProvideContext(environ=dict(MASTER=secret), local_state_file=local_state_file, config=config)
        provider.provide(requirement, context=context)
        assert 'FOO' in context.environ
        assert 'from_default' == context.environ['FOO']

    with_directory_contents(dict(), check_env_var_provider)


def test_env_var_provider_with_unencrypted_default_value_in_project_file_for_encrypted_requirement():
    # the idea here is that if you want to put an unencrypted
    # password in the file, we aren't going to be annoying and
    # stop you.
    def check_env_var_provider(dirname):
        provider = EnvVarProvider()
        requirement = _load_env_var_requirement(dirname, "FOO_SECRET")
        assert requirement.encrypted
        assert dict(default='from_default') == requirement.options
        local_state_file = LocalStateFile.load_for_directory(dirname)
        config_context = ProviderConfigContext(dict(), local_state_file, requirement)
        config = provider.read_config(config_context)
        context = ProvideContext(environ=dict(), local_state_file=local_state_file, config=config)
        provider.provide(requirement, context=context)
        assert 'FOO_SECRET' in context.environ
        assert 'from_default' == context.environ['FOO_SECRET']

    with_directory_contents(
        {PROJECT_FILENAME: """
runtime:
  FOO_SECRET:
    default: from_default
"""}, check_env_var_provider)


def test_env_var_provider_with_value_set_in_environment():
    def check_env_var_provider(dirname):
        provider = EnvVarProvider()
        requirement = _load_env_var_requirement(dirname, "FOO")
        local_state_file = LocalStateFile.load_for_directory(dirname)
        config_context = ProviderConfigContext(dict(), local_state_file, requirement)
        config = provider.read_config(config_context)
        assert dict() == config
        context = ProvideContext(environ=dict(FOO='from_environ'), local_state_file=local_state_file, config=config)
        provider.provide(requirement, context=context)
        assert 'FOO' in context.environ
        assert 'from_environ' == context.environ['FOO']

    # set a default to be sure we prefer 'environ' instead
    with_directory_contents(
        {PROJECT_FILENAME: """
runtime:
  FOO:
    default: from_default
"""}, check_env_var_provider)


def test_env_var_provider_with_value_set_in_local_state():
    def check_env_var_provider(dirname):
        provider = EnvVarProvider()
        requirement = _load_env_var_requirement(dirname, "FOO")
        local_state_file = LocalStateFile.load_for_directory(dirname)
        config_context = ProviderConfigContext(dict(), local_state_file, requirement)
        config = provider.read_config(config_context)
        assert dict(value="from_local_state") == config
        # set an environ to be sure we override it with local state
        context = ProvideContext(environ=dict(FOO='from_environ'), local_state_file=local_state_file, config=config)
        provider.provide(requirement, context=context)
        assert 'FOO' in context.environ
        assert 'from_local_state' == context.environ['FOO']

    with_directory_contents(
        {PROJECT_FILENAME: """
runtime:
  FOO:
    default: from_default
    """,
         LOCAL_STATE_DIRECTORY + "/" + LOCAL_STATE_FILENAME: """
variables:
  FOO: from_local_state
"""}, check_env_var_provider)


def test_env_var_provider_with_encrypted_default_value_in_local_state():
    def check_env_var_provider(dirname):
        # Save a default value which is encrypted and the key is in var MASTER
        local_state_file = LocalStateFile.load_for_directory(dirname)
        secret = "boo"
        encrypted = encrypt_string("from_local_state", secret)
        local_state_file.set_value(['variables', 'FOO_SECRET'], dict(key='MASTER', encrypted=encrypted))
        local_state_file.save()

        provider = EnvVarProvider()
        requirement = _load_env_var_requirement(dirname, "FOO_SECRET")
        assert requirement.encrypted
        assert dict(default='from_default') == requirement.options
        assert ('MASTER', ) == provider.missing_env_vars_to_configure(requirement, dict(), local_state_file)
        assert ('MASTER', ) == provider.missing_env_vars_to_provide(requirement, dict(), local_state_file)

        config_context = ProviderConfigContext(dict(MASTER=secret), local_state_file, requirement)
        assert () == provider.missing_env_vars_to_configure(requirement, config_context.environ, local_state_file)
        assert () == provider.missing_env_vars_to_provide(requirement, config_context.environ, local_state_file)
        config = provider.read_config(config_context)
        context = ProvideContext(environ=config_context.environ, local_state_file=local_state_file, config=config)
        provider.provide(requirement, context=context)
        assert 'FOO_SECRET' in context.environ
        assert 'from_local_state' == context.environ['FOO_SECRET']

    with_directory_contents(
        {PROJECT_FILENAME: """
runtime:
  FOO_SECRET:
    default: from_default
"""}, check_env_var_provider)


def test_env_var_provider_with_missing_encrypted_field_in_project_file():
    def check_env_var_provider(dirname):
        provider = EnvVarProvider()
        requirement = _load_env_var_requirement(dirname, "FOO")
        assert dict(default=dict(key='MASTER_PASSWORD')) == requirement.options
        local_state_file = LocalStateFile.load_for_directory(dirname)
        config_context = ProviderConfigContext(dict(), local_state_file, requirement)
        config = provider.read_config(config_context)
        context = ProvideContext(environ=dict(), local_state_file=local_state_file, config=config)
        provider.provide(requirement, context=context)
        assert 'FOO' not in context.environ
        assert ["No 'encrypted' field in the default value of FOO"] == context.errors

    with_directory_contents(
        {PROJECT_FILENAME: """
runtime:
  FOO:
    default: { key: 'MASTER_PASSWORD' }
"""}, check_env_var_provider)


def test_env_var_provider_with_missing_key_field_in_project_file():
    def check_env_var_provider(dirname):
        provider = EnvVarProvider()
        requirement = _load_env_var_requirement(dirname, "FOO")
        assert dict(default=dict(encrypted='abcdefg')) == requirement.options
        local_state_file = LocalStateFile.load_for_directory(dirname)
        config_context = ProviderConfigContext(dict(), local_state_file, requirement)
        config = provider.read_config(config_context)
        context = ProvideContext(environ=dict(), local_state_file=local_state_file, config=config)
        provider.provide(requirement, context=context)
        assert 'FOO' not in context.environ
        assert 1 == len(context.errors)
        assert "Value of 'FOO' should be a string" in context.errors[0]

    with_directory_contents(
        {PROJECT_FILENAME: """
runtime:
  FOO:
    default: { encrypted: 'abcdefg' }
"""}, check_env_var_provider)


def test_env_var_provider_with_list_valued_default_project_file():
    def check_env_var_provider_with_list_default(dirname):
        provider = EnvVarProvider()
        requirement = _load_env_var_requirement(dirname, "FOO")
        assert dict(default=[]) == requirement.options
        local_state_file = LocalStateFile.load_for_directory(dirname)
        config_context = ProviderConfigContext(dict(), local_state_file, requirement)
        config = provider.read_config(config_context)
        context = ProvideContext(environ=dict(), local_state_file=local_state_file, config=config)
        provider.provide(requirement, context=context)
        assert 'FOO' not in context.environ
        assert 1 == len(context.errors)
        assert "Value of 'FOO' should be a string" in context.errors[0]

    with_directory_contents({PROJECT_FILENAME: """
runtime:
  FOO:
    default: []
"""}, check_env_var_provider_with_list_default)


def test_env_var_provider_with_number_valued_default_project_file():
    def check_env_var_provider_with_number_default(dirname):
        provider = EnvVarProvider()
        requirement = _load_env_var_requirement(dirname, "FOO")
        assert dict(default=42) == requirement.options
        local_state_file = LocalStateFile.load_for_directory(dirname)
        config_context = ProviderConfigContext(dict(), local_state_file, requirement)
        config = provider.read_config(config_context)
        context = ProvideContext(environ=dict(), local_state_file=local_state_file, config=config)
        provider.provide(requirement, context=context)
        assert 'FOO' in context.environ
        assert 0 == len(context.errors)
        assert context.environ['FOO'] == "42"
        assert isinstance(context.environ['FOO'], str)

    with_directory_contents({PROJECT_FILENAME: """
runtime:
  FOO:
    default: 42
"""}, check_env_var_provider_with_number_default)


def test_env_var_provider_configure_local_state_value():
    def check_env_var_provider_config_local_state(dirname):
        provider = EnvVarProvider()
        requirement = _load_env_var_requirement(dirname, "FOO")
        local_state_file = LocalStateFile.load_for_directory(dirname)
        config_context = ProviderConfigContext(dict(), local_state_file, requirement)
        config = provider.read_config(config_context)
        assert dict() == config

        assert local_state_file.get_value(['variables', 'FOO']) is None

        provider.set_config_values_as_strings(config_context, dict(value="bar"))

        assert local_state_file.get_value(['variables', 'FOO']) == "bar"
        local_state_file.save()

        local_state_file_2 = LocalStateFile.load_for_directory(dirname)
        assert local_state_file_2.get_value(['variables', 'FOO']) == "bar"

        # setting empty string = unset
        provider.set_config_values_as_strings(config_context, dict(value=""))
        assert local_state_file.get_value(['variables', 'FOO']) is None

        local_state_file.save()

        local_state_file_3 = LocalStateFile.load_for_directory(dirname)
        assert local_state_file_3.get_value(['variables', 'FOO']) is None

    with_directory_contents({PROJECT_FILENAME: """
runtime:
  - FOO
"""}, check_env_var_provider_config_local_state)


def test_env_var_provider_config_html():
    def check_env_var_provider_config(dirname):
        provider = EnvVarProvider()
        requirement = _load_env_var_requirement(dirname, "FOO")
        local_state_file = LocalStateFile.load_for_directory(dirname)
        config_context = ProviderConfigContext(dict(), local_state_file, requirement)
        config = provider.read_config(config_context)
        assert dict() == config

        # config html when variable is unset
        status = requirement.check_status(dict())
        html = provider.config_html(config_context, status)
        assert 'Use this value:' in html

        # config html when variable is set
        status = requirement.check_status(dict(FOO='from_environ'))
        html = provider.config_html(config_context, status)
        assert 'Use this value instead:' in html

    # set a default to be sure we prefer 'environ' instead
    with_directory_contents({PROJECT_FILENAME: """
runtime:
  - FOO
"""}, check_env_var_provider_config)


def test_fail_to_find_providers_by_service():
    registry = PluginRegistry()
    found = registry.find_providers_by_service(requirement=None, service="nope")
    assert 0 == len(found)


def test_provide_context_properties():
    def check_provide_contents(dirname):
        environ = dict(foo='bar')
        local_state_file = LocalStateFile.load_for_directory(dirname)
        context = ProvideContext(environ=environ, local_state_file=local_state_file, config=dict(foo=42))
        assert dict(foo='bar') == context.environ
        assert [] == context.errors
        context.append_error("foo")
        context.append_error("bar")
        assert ["foo", "bar"] == context.errors

        assert [] == context.logs
        context.append_log("foo")
        context.append_log("bar")
        assert ["foo", "bar"] == context.logs

        assert dict(foo=42) == context.config

    with_directory_contents(dict(), check_provide_contents)


def test_provide_context_ensure_work_directory():
    def check_provide_contents(dirname):
        environ = dict()
        local_state_file = LocalStateFile.load_for_directory(dirname)
        context = ProvideContext(environ=environ, local_state_file=local_state_file, config={})
        workpath = context.ensure_work_directory("foo")
        assert os.path.isdir(workpath)
        parent = os.path.dirname(workpath)
        assert parent.endswith("/run")
        parent = os.path.dirname(parent)
        assert parent.endswith("/.anaconda")

        # be sure we can create if it already exists
        workpath2 = context.ensure_work_directory("foo")
        assert os.path.isdir(workpath2)
        assert workpath == workpath2

    with_directory_contents(dict(), check_provide_contents)


def test_provide_context_ensure_work_directory_cannot_create(monkeypatch):
    def mock_makedirs(path, mode=0):
        raise IOError("this is not EEXIST")

    monkeypatch.setattr("os.makedirs", mock_makedirs)

    def check_provide_contents(dirname):
        environ = dict()
        local_state_file = LocalStateFile.load_for_directory(dirname)
        context = ProvideContext(environ=environ, local_state_file=local_state_file, config={})
        with pytest.raises(IOError) as excinfo:
            context.ensure_work_directory("foo")
        assert "this is not EEXIST" in repr(excinfo.value)

    with_directory_contents(dict(), check_provide_contents)


def test_provide_context_transform_service_run_state():
    def check_provide_contents(dirname):
        environ = dict()
        local_state_file = LocalStateFile.load_for_directory(dirname)
        local_state_file.set_service_run_state("myservice", dict(port=42))
        context = ProvideContext(environ=environ, local_state_file=local_state_file, config={})

        def transform_it(state):
            assert 42 == state['port']
            state['port'] = 43
            state['foo'] = 'bar'
            return 1234

        result = context.transform_service_run_state("myservice", transform_it)
        assert 1234 == result
        assert dict(port=43, foo='bar') == local_state_file.get_service_run_state("myservice")

    with_directory_contents(dict(), check_provide_contents)

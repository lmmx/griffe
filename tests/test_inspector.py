"""Test inspection mechanisms."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from griffe.agents.inspector import inspect
from griffe.tests import temporary_inspected_module, temporary_pypackage


# Use this function to clear sys.modules from a module and its submodules
# after having used `temporary_pypackage` and `inspect` together.
def _clear_sys_modules(name: str) -> None:
    for module in list(sys.modules.keys()):
        if module == name or module.startswith(f"{name}."):
            sys.modules.pop(module, None)


def test_annotations_from_builtin_types() -> None:
    """Assert builtin types are correctly transformed to annotations."""
    with temporary_inspected_module("def func(a: int) -> str: pass") as module:
        func = module["func"]
        assert func.parameters[0].name == "a"
        assert func.parameters[0].annotation.name == "int"
        assert func.returns.name == "str"


def test_annotations_from_classes() -> None:
    """Assert custom classes are correctly transformed to annotations."""
    with temporary_inspected_module("class A: pass\ndef func(a: A) -> A: pass") as module:
        func = module["func"]
        assert func.parameters[0].name == "a"
        param = func.parameters[0].annotation
        assert param.name == "A"
        assert param.canonical_path == f"{module.name}.A"
        returns = func.returns
        assert returns.name == "A"
        assert returns.canonical_path == f"{module.name}.A"


def test_class_level_imports() -> None:
    """Assert annotations using class-level imports are resolved."""
    with temporary_inspected_module(
        """
        class A:
            from io import StringIO
            def method(self, p: StringIO):
                pass
        """,
    ) as module:
        method = module["A.method"]
        name = method.parameters["p"].annotation
        assert name.name == "StringIO"
        assert name.canonical_path == "io.StringIO"


def test_missing_dependency() -> None:
    """Assert missing dependencies are handled during dynamic imports."""
    with temporary_pypackage("package", ["module.py"]) as tmp_package:
        filepath = Path(tmp_package.path, "module.py")
        filepath.write_text("import missing")
        with pytest.raises(ImportError, match="ModuleNotFoundError: No module named 'missing'"):
            inspect("package.module", filepath=filepath, import_paths=[tmp_package.tmpdir])
    _clear_sys_modules("package")


def test_inspect_properties_as_attributes() -> None:
    """Assert properties are created as attributes and not functions."""
    with temporary_inspected_module(
        """
        try:
            from functools import cached_property
        except ImportError:
            from cached_property import cached_property

        class C:
            @property
            def prop(self) -> bool:
                return True
            @cached_property
            def cached_prop(self) -> int:
                return 0
        """,
    ) as module:
        assert module["C.prop"].is_attribute
        assert "property" in module["C.prop"].labels
        assert module["C.cached_prop"].is_attribute
        assert "cached" in module["C.cached_prop"].labels


def test_inspecting_module_importing_other_module() -> None:
    """Assert aliases to modules are correctly inspected and aliased."""
    with temporary_inspected_module("import itertools as it") as module:
        assert module["it"].is_alias
        assert module["it"].target_path == "itertools"


def test_inspecting_parameters_with_functions_as_default_values() -> None:
    """Assert functions as default parameter values are serialized with their name."""
    with temporary_inspected_module("def func(): ...\ndef other_func(f=func): ...") as module:
        default = module["other_func"].parameters["f"].default
    assert default == "func"


def test_inspecting_package_and_module_with_same_names() -> None:
    """Package and module having same name shouldn't cause issues."""
    with temporary_pypackage("package", {"package.py": "a = 0"}) as tmp_package:
        inspect("package.package", filepath=tmp_package.path / "package.py", import_paths=[tmp_package.tmpdir])
    _clear_sys_modules("package")


def test_inspecting_module_with_submodules() -> None:
    """Inspecting a module shouldn't register any of its submodules if they're not imported."""
    with temporary_pypackage("pkg", ["mod.py"]) as tmp_package:
        pkg = inspect("pkg", filepath=tmp_package.path / "__init__.py")
    assert "mod" not in pkg.members
    _clear_sys_modules("pkg")


def test_inspecting_module_with_imported_submodules() -> None:
    """When inspecting a package on the disk, direct submodules should be skipped entirely."""
    with temporary_pypackage(
        "pkg",
        {
            "__init__.py": "from pkg import subpkg\nfrom pkg.subpkg import mod",
            "subpkg/__init__.py": "a = 0",
            "subpkg/mod.py": "b = 0",
        },
    ) as tmp_package:
        pkg = inspect("pkg", filepath=tmp_package.path / "__init__.py")
    assert "subpkg" not in pkg.members
    assert "mod" in pkg.members
    assert pkg["mod"].is_alias
    assert pkg["mod"].target_path == "pkg.subpkg.mod"
    _clear_sys_modules("pkg")


def test_inspecting_objects_from_private_builtin_stdlib_moduless() -> None:
    """Inspect objects from private built-in modules in the standard library."""
    ast = inspect("ast")
    assert "Assign" in ast.members
    assert not ast["Assign"].is_alias

    ast = inspect("_ast")
    assert "Assign" in ast.members
    assert not ast["Assign"].is_alias

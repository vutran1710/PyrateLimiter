"""Config file for Sphinx documentation"""
from importlib.metadata import version as pkg_version
from pathlib import Path

PROJECT_DIR = Path(__file__).parent.parent.absolute()
PACKAGE_DIR = str(PROJECT_DIR / "pyrate_limiter")
MODULE_DOCS_DIR = "modules"

# General information about the project.
exclude_patterns = ["_build"]
master_doc = "index"
needs_sphinx = "4.0"
source_suffix = [".rst", ".md"]
templates_path = ["_templates"]
project = "pyrate-limiter"
version = release = version = pkg_version("pyrate-limiter")

# Sphinx extensions
extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.autosummary",
    "sphinx.ext.intersphinx",
    "sphinx.ext.napoleon",
    "sphinx_autodoc_typehints",
    "sphinx_copybutton",
    "sphinxcontrib.apidoc",
    "myst_parser",
]

myst_enable_extensions = ["html_image"]

# Enable automatic links to other projects' Sphinx docs
intersphinx_mapping = {
    "python": ("https://docs.python.org/3", None),
}

# napoleon settings
napoleon_google_docstring = True
napoleon_include_init_with_doc = True
numpydoc_show_class_members = False

# copybutton settings: Strip prompt text when copying code blocks
copybutton_prompt_text = r">>> |\.\.\. |\$ "
copybutton_prompt_is_regexp = True

# Disable autodoc's built-in type hints, and use sphinx_autodoc_typehints extension instead
autodoc_typehints = "none"

# Auto-generage module docs with sphinx-apidoc
apidoc_module_dir = PACKAGE_DIR
apidoc_output_dir = MODULE_DOCS_DIR
apidoc_module_first = True
apidoc_separate_modules = True
apidoc_toc_file = False

# HTML general settings
html_show_sphinx = False
pygments_style = "friendly"
pygments_dark_style = "material"

# HTML theme settings
html_logo = "_static/logo.png"
html_static_path = ["_static"]
html_theme = "furo"
html_theme_options = {
    "sidebar_hide_name": True,
}

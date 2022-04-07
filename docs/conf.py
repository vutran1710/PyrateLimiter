"""Config file for Sphinx documentation"""
import tomlkit


# Get project metadata from pyproject.toml
def get_project_metadata():

    with open("../pyproject.toml") as pyproject:
        file_contents = pyproject.read()
    return tomlkit.parse(file_contents)["tool"]["poetry"]


# General information about the project.
project_metadata = get_project_metadata()
exclude_patterns = ["_build"]
master_doc = "index"
needs_sphinx = "4.0"
source_suffix = [".rst", ".md"]
templates_path = ["_templates"]
project = str(project_metadata["name"])
version = release = version = str(project_metadata["version"])

# Sphinx extensions
extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.autosummary",
    "sphinx.ext.intersphinx",
    "sphinx.ext.napoleon",
    "sphinx_autodoc_typehints",
    "sphinx_copybutton",
    "myst_parser",
]

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

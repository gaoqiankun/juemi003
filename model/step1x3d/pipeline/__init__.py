# Lazy package — do not eagerly import submodules here.
# provider.py imports geometry/texture pipelines directly via importlib
# to avoid loading training-only dependencies (pytorch3d etc.) at startup.

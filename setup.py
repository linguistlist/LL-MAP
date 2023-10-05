from setuptools import setup


setup(
    name='cldfbench_llmap',
    py_modules=['cldfbench_llmap'],
    include_package_data=True,
    zip_safe=False,
    entry_points={
        'cldfbench.dataset': [
            'llmap=cldfbench_llmap:Dataset',
        ],
        'cldfbench.commands': [
            'llmap=llmapcommands',
        ],
    },
    install_requires=[
        'cldfbench',
    ],
    extras_require={
        'test': [
            'pytest-cldf',
        ],
    },
)

waykit
======

waykit is a python tool to generate location metatata like peaks, huts and
other pois for a given gpx file

## Usage

You can run the tool directly from github with [uvx](https://docs.astral.sh/uv/guides/tools/#requesting-different-sources)

```
uvx git+https://github.com/hoffmann/waykit -o output.geojson input.gpx
```

To install and run the package from [pypi](https://pypi.org/project/waykit/):

```
# use your preferred tool to create a virtual environment
pip install waykit
waykit -o output.geojson input.gpx 
``` 

You can also clone the repository and run it locally

```
uv run waykit -o output.geojson input.gpx 
```


## run the tests

If you have just installed you can use the following

```
just test
```

otherwise check the command in the `justfile` to run the pytests

# gmtsar.py.docker.dev — GMTSAR Python framework Docker image.
#
# Build (run from REPO ROOT, not from this directory):
#   docker build -f gmtsar/python/docker/Dockerfile -t dunyuliu/gmtsar:latest .
#
# Run:
#   docker run --rm -it -v $PWD:/data dunyuliu/gmtsar:latest
#   (mount data dir as /data; orbits as /opt/gmtsar/orbits if needed)

FROM ubuntu:22.04
ENV DEBIAN_FRONTEND=noninteractive
ENV GMTSAR=/opt/gmtsar
ENV PATH=$GMTSAR/bin:$PATH

# Build + runtime dependencies. install.sh --ubuntu/--python would do the same
# apt installs, but keeping them inline here lets Docker cache this layer
# separately from the source copy below.
RUN apt-get update && apt-get install -y --no-install-recommends \
        python-is-python3 csh autoconf wget make git ghostscript \
        gcc g++ gfortran \
        libtiff5-dev libhdf5-dev libgmt-dev liblapack-dev \
        gmt gmt-dcw gmt-gshhg \
        python3-skimage python3-matplotlib python3-xarray python3-netcdf4 \
        python3-tk python3-numpy \
    && rm -rf /var/lib/apt/lists/*

# Copy the source tree and build in place. .dockerignore excludes work/, orbits/,
# dataset/, .git so the build context stays small.
COPY . /opt/gmtsar
WORKDIR /opt/gmtsar
RUN bash gmtsar/python/install.sh --build

# Working dir for user data (mount with `-v $PWD:/data`).
WORKDIR /data
VOLUME ["/data", "/opt/gmtsar/orbits"]

# Sanity check at image-build time — fails the build early if binaries missing.
RUN p2p_processing 2>&1 | head -1

CMD ["bash"]

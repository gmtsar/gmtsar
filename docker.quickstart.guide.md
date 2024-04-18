## Docker Quick Start Guide

A docker Ubuntu image that contains environments for GMTSAR is available through dunyuliu/gmtsar.ubuntu.py:v0.0.1. <br/>
If [Docker Desktop](https://www.docker.com/products/docker-desktop/) is installed locally, users can pull the image and run it as a container. <br/>

For Windows operating systems, if WSL is available, Docker Desktop will be installed in the C:/ drive. <br/>
The huge satellite data could be stored in different disks/drives, which can be mounted back to the docker container. <br/>

Currently, the image is v0.0.1 and 1 GB large. <br>

Below are detailed commands to pull and run the gmtsar.ubuntu.py image and how to mount external disks/drives. <br/>

# Windows OS

Open Powershell with admin access, then type the following command in the terminal.
```
docker run -it --name $gmtsar -v $GMTSAR.external.drive:$proxy.path dunyuliu/gmtsar.ubuntu.py:v0.0.1
```
where $gmtsar is the name of the container shown in the docker environment and Docker Desktop, say gmtsar.volume, and <br/>
$GMTSAR.external.drive is the path of the external drive to be mounted to the container, say D:/GMTSAR.data, and <br/>
$proxy.path is the proxy path of the external drive in the Ubuntu system, say /mount  . <br/>

Here is an example:
```
docker run -it --name gmtsar.volume -v D:/GMTSAR.docker.data:/mount dunyuliu/gmtsar.ubuntu.py:v0.0.1
```

NOTE: If you don't want to mount external disks/drives to the container, please don't add the flag -v and the following path. In this case, you will run everything inside the container, which is the C:/ drive and for GMTSAR, it may eat up disk space quickly <br/>

AFter running the command, you will see files downloaded, if the image is not available locally, and a container created. <br/>

Then, you can open a terminal in the container from the Docker Desktop and run it as a normal Ubuntu system.

csh utilities of GMTSAR would be reaily callable. New python utilites are under development. 

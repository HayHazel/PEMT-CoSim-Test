FROM ubuntu:jammy
SHELL ["/bin/bash", "-l", "-c"]

ARG DEBIAN_FRONTEND=noninteractive

RUN apt update
RUN apt install -y \
  python3-pip \
  git \
  libboost-dev \
  libboost-filesystem-dev \
  libboost-program-options-dev \
  libboost-test-dev \
  libzmq5-dev python3-dev \
  build-essential swig cmake git

RUN apt install -y nano libxtst6 libxi6 libxrender1 wget firefox

WORKDIR $HOME

# build + install HELICS
RUN git clone https://github.com/GMLC-TDC/HELICS
WORKDIR $HOME/HELICS
RUN mkdir -p build
WORKDIR $HOME/HELICS/build
RUN cmake ..
RUN make -j$(nproc)
RUN make install
RUN ldconfig
RUN echo "export LD_LIBRARY_PATH=/usr/local/lib" >> ~/.bashrc

WORKDIR $HOME

# install GridLAB-D
RUN wget https://github.com/gridlab-d/gridlab-d/releases/download/v5.1/GridLAB-D-5.1.0-Linux.deb
RUN dpkg -i GridLAB-D-5.1.0-Linux.deb

# install miniconda
RUN wget https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh
RUN bash Miniconda3-latest-Linux-x86_64.sh -b
RUN sed -e '/[ -z "$PS1" ] && return/s/^/#/g' -i /root/.bashrc

# install python requirements
RUN /root/miniconda3/bin/conda init bash
RUN conda create -n cosim python=3.10
RUN echo "conda activate cosim" >> ~/.bashrc
COPY requirements.txt .
RUN pip install -r ./requirements.txt
RUN emobpy create -n unused

RUN apt -y install openssh-server
RUN sed -i 's/\#PermitRootLogin.*/PermitRootLogin Yes/' /etc/ssh/sshd_config
RUN systemctl enable ssh & update-rc.d ssh defaults & systemctl enable ssh.socket & systemctl enable ssh.service
RUN echo "root:helics" | chpasswd
EXPOSE 22

ENTRYPOINT service ssh start && sleep infinity

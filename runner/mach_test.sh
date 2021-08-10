#!/bin/bash --login

#
# set verbose, exit on error
#
set -v
set -e

#
# set working directory
#
export WD=$PWD

#
# need gcc8, openmpi and hypre
#
module purge
module load gcc/8.1.0 openmpi/4.0.5 hypre/2.20.0
module load gnu_build/20210203
export CPATH=/hx/software/apps/openmpi/4.0.5/gcc8/include/

#
# need a python env with mpi4py and mkdocs 
#
eval "$(/anaconda3/bin/conda shell.bash hook)"
if conda env list | grep mach_test; then
    conda env remove -n mach_test
fi
if ! conda env list | grep mach_test; then
  conda create --yes -n mach_test python=3 cython swig
  conda activate mach_test
  pip install mkdocs
  export LDFLAGS+=" -shared"
  env MPICC=`which mpicc` pip install mpi4py
  env MPICC=`which mpicc` pip install petsc4py
  unset LDFLAGS
else
  conda activate mach_test
fi
export LD_LIBRARY_PATH="$LD_LIBRARY_PATH:$CONDA_PREFIX/lib/"

#
# build ESP
#
cd $WD
if [ ! -d "OpenCASCADE-7.4.1" ]; then
  #wget -nv https://acdl.mit.edu/esp/otherOCCs/OCC741lin64.tgz
  #tar -xzpf OCC741lin64.tgz
  #rm OCC741lin64.tgz
  tar -xzpf ~/dev/OCC741lin64.tgz
fi
if [ ! -d "EngSketchPad" ]; then
  git clone https://github.com/tuckerbabcock/EngSketchPad
fi

cd EngSketchPad/config
git checkout beta
git pull
./makeEnv $WD/OpenCASCADE-7.4.1
cd ..
source ESPenv.sh
cd src
make

#
# build PUMI
#
cd $WD
if [ ! -d "core" ]; then
  git clone https://github.com/tuckerbabcock/core
fi

cd core
git checkout egads-dev
git pull

if [ ! -d "build" ]; then
  mkdir build
fi
cd build
cat <<EOF > config_pumi.sh
cmake3 .. \\
  -DCMAKE_C_COMPILER="mpicc" \\
  -DCMAKE_POSITION_INDEPENDENT_CODE="YES" \\
  -DCMAKE_CXX_COMPILER="mpicxx" \\
  -DCMAKE_C_FLAGS="-O0 -g -Wall -fPIC" \\
  -DCMAKE_CXX_FLAGS="-O0 -g -Wall -std=c++11 -fPIC" \\
  -DSCOREC_ENABLE_CXX11="YES" \\
  -DENABLE_THREADS=OFF \\
  -DBUILD_SHARED_LIBS=False \\
  -DENABLE_ZOLTAN=OFF \\
  -DENABLE_EGADS=ON \\
  -DPUMI_USE_EGADSLITE=OFF \\
  -DEGADS_DIR="\$ESP_ROOT" \\
  -DCMAKE_INSTALL_PREFIX=\$PWD/install
EOF
source config_pumi.sh
make -j 4
make install

#
# build MFEM
#
cd $WD
if [ ! -d "mfem" ]; then
  git clone https://github.com/mfem/mfem
fi

cd mfem
git checkout odl
git pull

if [ ! -d "build" ]; then
  mkdir build
fi
cd build
cat <<EOF > config_mfem.sh
cmake3 .. \\
  -DCMAKE_BUILD_TYPE=Debug \\
  -DMFEM_USE_MPI=YES \\
  -DMFEM_USE_METIS_5=YES \\
  -DMFEM_DEBUG=YES \\
  -DMFEM_USE_PUMI=YES \\
  -DMFEM_ENABLE_EXAMPLES=NO \\
  -DMFEM_ENABLE_MINIAPPS=NO \\
  -DMETIS_DIR="/lib64/" \\
  -DHYPRE_DIR="/hx/software/apps/hypre/2.20.0/" \\
  -DPUMI_DIR="\$WD/core/build/install" \\
  -DCMAKE_POSITION_INDEPENDENT_CODE=YES 
EOF
source config_mfem.sh
make -j

#
# build Adept-2
#
cd $WD
if [ ! -d "Adept-2" ]; then
  git clone git@github.com:rjhogan/Adept-2
fi

cd Adept-2
git pull
touch README
aclocal; autoupdate; autoheader; autoconf
libtoolize; autoreconf -i
./configure --prefix="$PWD"
make
make check
set +e
make install
set -e

#
# build MACH
#
cd $WD
if [ ! -d "mach" ]; then
  git clone git@github.com:OptimalDesignLab/mach.git
fi

cd mach
git checkout dev
git pull

if [ ! -d "build" ]; then
  mkdir build
fi
cd build
cat <<EOF > mach_config.sh
cmake3 .. \\
 -DCMAKE_BUILD_TYPE="Release" \\
 -DADEPT_DIR="../Adept-2/" \\
 -DMFEM_DIR="../mfem/build/" \\
 -DPUMI_DIR="../core/build/install" \\
 -DEGADS_DIR="../EngSketchPad/" \\
 -DBUILD_TESTING="YES" \\
 -DBUILD_PYTHON_WRAPPER="YES"
EOF
set +e
source mach_config.sh
set -e
source mach_config.sh
make -j
make build_tests -j
ctest --output-on-failure
make install

#
# install OpenMDAO
#
cd $WD
if [ ! -d "OpenMDAO" ]; then
  git clone git@github.com:OpenMDAO/OpenMDAO
fi

cd OpenMDAO
git pull
pip install --upgrade -e .[test]

#
# test mach python wrapper
#
cd $WD
cd mach
pip install --upgrade -e .

conda list

# disabled for now
#testflo --timeout=120 -vs mach/test


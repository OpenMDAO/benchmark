#!/bin/bash --login

#
# set verbose, exit on error
#
set -e

#
# set working directory
#
export WD=$PWD

#
# if we have 'module', use system assets
#
export MODULE=`command -v module`
if [[ "$MODULE" == "module" ]]; then
  module purge

  module load miniforge/4.10.3

  module load openmpi/4.1.4/gnu/11.2.0
  export MPICC=/cryo/sw/openmpi/4.1.4/gnu/11.2.0/bin/mpicc
  export MPICXX=/cryo/sw/openmpi/4.1.4/gnu/11.2.0/bin/mpicxx

  export HYPRE_DIR=/hx/software/apps/hypre/2.20.0/

  export J='-j'
else
  sudo apt -qq install build-essential cmake liblapack-dev libblas-dev libz-dev openmpi-bin libopenmpi-dev libmetis-dev libhypre-dev

  export MPICC=/usr/bin/mpicc
  export MPICXX=/usr/bin/mpicxx
  export METIS_DIR=/usr
  export HYPRE_DIR=/usr/include/hypre/
  # export HYPRE_INCLUDE_DIRS=/usr/include/hypre/

  rm -rf $WD/tmp
  mkdir $WD/tmp
  export TMP=$WD/tmp
  export TMPDIR=$WD/tmp

  # running make with multiple threads on GitHub actions results in the workflow being killed with error code 143 (resources exhausted)
  export J=
fi

export PRTE_MCA_rmaps_default_mapping_policy=:oversubscribe
export OMPI_MCA_rmaps_base_oversubscribe=1
export OMPI_MCA_btl=^openib

eval "$(conda shell.bash hook)"

#
# need a python environment with metis, mpi4py and mkdocs
#

echo "#########################"
echo "Create Environment"
echo "#########################"
if conda env list | grep miso_test; then
    conda env remove -n miso_test -y
fi
if ! conda env list | grep miso_test; then

  conda create -q -y -n miso_test python=3.10 cython swig
  conda activate miso_test

  # conda install sysroot_linux-64 gxx_linux-64 libgcc gfortran metis hypre openmpi-mpicc
  # export METIS_DIR=$CONDA_PREFIX
  # export HYPRE_DIR=$CONDA_PREFIX
  # export MPICC=$CONDA_PREFIX/bin/mpicc
  # export MPICXX=$CONDA_PREFIX/bin/mpicxx

  if [[ "$MODULE" == "module" ]]; then
    conda install metis
  fi

  pip install --upgrade pip
  
  pip install mpi4py mkdocs
else
  conda activate miso_test
fi

if conda list | grep metis; then
  export METIS_DIR=$CONDA_PREFIX
fi

echo "#########################"
echo "Install PETSc from source"
echo "#########################"
if [ ! -d "petsc-3.19.2" ]; then
  if [ ! -f "$HOME/petsc-3.19.2.tgz" ]; then
    echo "Downloading PETSc..."
    wget -nv https://web.cels.anl.gov/projects/petsc/download/release-snapshots/petsc-3.19.2.tar.gz -O $HOME/petsc-3.19.2.tgz
  fi
  tar -xzpf $HOME/petsc-3.19.2.tgz
fi
cd petsc-3.19.2
./configure
make all check

echo "#########################"
echo "Build ESP"
echo "#########################"
cd $WD
if [ ! -d "OpenCASCADE-7.4.1" ]; then
  if [ ! -f "$HOME/OCC741lin64.tgz" ]; then
    echo "Downloading OpenCASCADE-7.4.1"
    wget -nv https://acdl.mit.edu/esp/otherOCCs/OCC741lin64.tgz -O $HOME/OCC741lin64.tgz
  fi
  tar -xzpf $HOME/OCC741lin64.tgz
  rm $HOME/OCC741lin64.tgz
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
make -s

echo "#########################"
echo "Build PUMI"
echo "#########################"
cd $WD
if [ ! -d "core" ]; then
  git clone https://github.com/tuckerbabcock/core
fi

cd core
git checkout egads-dev
git pull
git submodule update --init --recursive

if [ ! -d "build" ]; then
  mkdir build
fi
cd build
cat <<EOF > config_pumi.sh
cmake .. \\
  -DCMAKE_C_COMPILER="$MPICC" \\
  -DCMAKE_CXX_COMPILER="$MPICXX" \\
  -DCMAKE_POSITION_INDEPENDENT_CODE="YES" \\
  -DSCOREC_CXX_OPTIMIZE=ON \\
  -DSCOREC_CXX_SYMBOLS=ON \\
  -DSCOREC_CXX_WARNINGS=OFF \\
  -DBUILD_SHARED_LIBS=True \\
  -DSCOREC_ENABLE_CXX11="YES" \\
  -DENABLE_THREADS=OFF \\
  -DENABLE_ZOLTAN=OFF \\
  -DENABLE_EGADS=ON \\
  -DPUMI_USE_EGADSLITE=OFF \\
  -DEGADS_DIR="\$ESP_ROOT" \\
  -DCMAKE_INSTALL_PREFIX=./install
EOF
source config_pumi.sh
make -s $J
make install

echo "#########################"
echo "Build MFEM"
echo "#########################"
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
cmake .. \\
  -DCMAKE_BUILD_TYPE=Debug \\
  -DMFEM_USE_MPI=YES \\
  -DMFEM_USE_METIS_5=YES \\
  -DMFEM_DEBUG=YES \\
  -DMFEM_USE_PUMI=YES \\
  -DMFEM_ENABLE_EXAMPLES=NO \\
  -DMFEM_ENABLE_MINIAPPS=NO \\
  -DMETIS_DIR="$METIS_DIR" \\
  -DHYPRE_DIR="$HYPRE_DIR" \\
  -DPUMI_DIR="\$WD/core/build/install" \\
  -DCMAKE_POSITION_INDEPENDENT_CODE=YES
EOF
source config_mfem.sh
make -s $J

echo "#########################"
echo "Build Adept-2"
echo "#########################"
cd $WD
if [ ! -d "Adept-2" ]; then
  git clone git@github.com:rjhogan/Adept-2
fi

cd Adept-2
git pull
touch README
aclocal; autoupdate; autoheader; autoconf
libtoolize; autoreconf -i
./configure --prefix="$PWD/../adept_install"
make -s
make check
set +e
make install
set -e

echo "#########################"
echo "Build MISO"
echo "#########################"
cd $WD
if [ ! -d "miso" ]; then
  git clone git@github.com:OptimalDesignLab/miso.git
fi

cd miso
git checkout dev
git pull

sed -i 's/mach/miso/g' ./miso/pyMISO/CMakeLists.txt
sed -i 's/Mach/MISO/g' ./miso/pyMISO/CMakeLists.txt

if [ ! -d "build" ]; then
  mkdir build
fi
cd build
cat <<EOF > miso_config.sh
cmake .. \\
 -DCMAKE_BUILD_TYPE="Release" \\
 -DAdept_ROOT="$PWD/../../adept_install/" \\
 -DMFEM_DIR="$PWD/../../mfem/build/" \\
 -DPUMI_DIR="$PWD/../../core/build/install" \\
 -DEGADS_DIR="$PWD/../../EngSketchPad/" \\
 -DBUILD_TESTING="YES" \\
 -DBUILD_PYTHON_WRAPPER="YES"
EOF
set +e
source miso_config.sh
set -e
source miso_config.sh
make -s $J
make build_tests
ctest --output-on-failure
make install

echo "#########################"
echo "Install OpenMDAO"
echo "#########################"

cd $WD
if [ ! -d "OpenMDAO" ]; then
  git clone git@github.com:OpenMDAO/OpenMDAO
fi

cd OpenMDAO
git pull
pip install --upgrade -e .[test]

echo "#########################"
echo "Test miso python wrapper"
echo "#########################"
cd $WD
cd miso
pip install --upgrade -e .

conda list

# disabled for now
#testflo --timeout=120 -vs miso/test

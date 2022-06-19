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
# need gcc8, openmpi and hypre
#
module purge
module load miniforge/4.10.3
eval "$(conda shell.bash hook)"

module load openmpi/4.1.3/gnu/8.5.0
export PATH=$PATH:/cryo/sw/openmpi/4.1.3/gnu/8.5.0/bin
export CPATH=$CPATH:/cryo/sw/openmpi/4.1.3/gnu/8.5.0/include

#
# need a python environment with mpi4py and mkdocs 
#
conda deactivate
conda deactivate

echo "#########################"
echo "Create Environment"
echo "#########################"
if conda env list | grep mach_test; then
    conda env remove -n mach_test
fi
if ! conda env list | grep mach_test; then
  conda create --yes -n mach_test python=3 gxx_linux-64=8.4.0 sysroot_linux-64=2.17 cmake cython swig
  conda activate mach_test
  conda install --yes -c conda-forge mpi4py petsc4py hypre
  pip install mkdocs
else
  conda activate mach_test
fi

echo "#########################"
echo "Build ESP"
echo "#########################"
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
  -DCMAKE_C_COMPILER="mpicc" \\
  -DCMAKE_POSITION_INDEPENDENT_CODE="YES" \\
  -DCMAKE_CXX_COMPILER="mpicxx" \\
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
make -j 4
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
  -DMETIS_DIR="/lib64/" \\
  -DHYPRE_DIR="/hx/software/apps/hypre/2.20.0/" \\
  -DPUMI_DIR="\$WD/core/build/install" \\
  -DCMAKE_POSITION_INDEPENDENT_CODE=YES 
EOF
source config_mfem.sh
make -j

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
./configure --prefix="$PWD"
make
make check
set +e
make install
set -e

echo "#########################"
echo "Build MACH"
echo "#########################"
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
cmake .. \\
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
echo "Test mach python wrapper"
echo "#########################"
cd $WD
cd mach
pip install --upgrade -e .

conda list

# disabled for now
#testflo --timeout=120 -vs mach/test

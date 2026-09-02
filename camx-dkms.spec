# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause

# Source-only payload: no ELF to strip, no build-ids to link.
%global debug_package %{nil}
%global _build_id_links none

%global mod_name  camx
%global dkms_src  %{_usrsrc}/%{mod_name}-%{version}

# The upstream repo and the root directory inside its tag archive are named
# camera-driver, not camx-dkms. Source0 and %%prep both use this name.
%global upstream_name camera-driver

# Camera targets to declare in dkms.conf's module table. Hardcoded, mirroring
# The package target list is maintained explicitly because selecting which
# camera targets ship is an RPM packaging decision.
#
# Update camx_targets when adding or removing a camera target.
#
# %%install validates this list against SUPPORTED_ARCH and
# config/<target>-camera.mk before creating dkms.conf.
%global camx_targets qcm6490 qcs9100 qcs615 x1e80100

Name:           camx-dkms
Version:        1.0.5
Release:        1%{?dist}
Summary:        Qualcomm CamX camera kernel driver (DKMS source)

License:        GPL-2.0-only
URL:            https://github.com/qualcomm-linux/camera-driver

# Fetch the tagged camera-driver source directly. The #/ fragment gives the
# downloaded file the basename expected by rpmbuild and the source resolver.
# GitHub's archive root is camera-driver-%%{version}/.
Source0:        %{url}/archive/refs/tags/v%{version}.tar.gz#/%{upstream_name}-%{version}.tar.gz

# The driver is Qualcomm arm64 SoC only; every config/<arch>-camera.mk sets
# CONFIG_ARCH_QCOM-gated options and dkms.conf enforces the same at build time.
ExclusiveArch:  aarch64

# No BuildRequires at all, on purpose. %%build compiles nothing and %%install
# only shells out to tar / sed / install, all from coreutils and tar which are
# in the minimal buildroot. Adding kernel headers or a toolchain here would slow
# the build and wrongly imply the module is built at packaging time.

# Runtime deps are the DKMS toolchain, needed by %%post and by every subsequent
# kernel upgrade -- not at rpmbuild time.
#
# dkms lives in EPEL on CentOS/RHEL 10, not in the base repos. It is listed as
# a hard Requires (not epel-release) so the failure mode is an honest
# unresolvable dependency at `dnf install` time rather than a package that
# installs cleanly and then cannot build anything. Enable EPEL, or carry dkms
# in the product repo, before installing this package.
Requires:       epel-release
Requires:       dkms >= 2.8
Requires:       gcc
Requires:       make

# kernel-devel must be present for the arch's running kernel before DKMS can
# build. Weak, not hard: an image build may stage headers under a different
# package name, and %%post degrades to a warning rather than failing the
# transaction when no headers are found.
Recommends:     kernel-devel >= 6.16

%description
Qualcomm CamX camera kernel driver (Spectra ISP, IFE/IPE/BPS, ICP, JPEG, LRME
and the sensor sub-devices) packaged as DKMS source. The module is built on the
target machine against its installed kernel headers, and rebuilt automatically
on kernel upgrades.

One module is produced per supported camera target, named camera_<target>.ko and
installed under /updates/camera. The packaged targets are qcm6490, qcs9100,
qcs615 and x1e80100.

%package -n camx-linux-devel
Summary:        CamX kernel UAPI headers
BuildArch:      noarch
Provides:       camx-linux-dev = %{version}-%{release}
Provides:       camx-uapi-dev = %{version}-%{release}

%description -n camx-linux-devel
Kernel UAPI headers for the CamX camera driver, as consumed by the CamX
userspace stack. Installed under %{_includedir}/camx/, one directory per driver
tree: camera/ for the common driver and camera-kodiak/ for the Kodiak variant.

Headers only -- installing this package does not build or load any module.

%prep
%autosetup -n %{upstream_name}-%{version}

%build
# Deliberately empty. DKMS builds the module on the target; see the header
# comment. The module is compiled later by DKMS on the target device.

%install
# ── Target list ───────────────────────────────────────────────────────────────
# Validate the explicit target list before generating dkms.conf. These checks
# prevent a package from declaring modules that the source tree cannot build.
TARGETS="%{camx_targets}"
if [ -z "${TARGETS}" ]; then
    echo "ERROR: camx_targets is empty -- nothing to package" >&2
    exit 1
fi

MAKEFILE_ARCH=$(sed -n 's/^[[:space:]]*SUPPORTED_ARCH[[:space:]]*=[[:space:]]*//p' Makefile | head -1)
if [ -z "${MAKEFILE_ARCH}" ]; then
    echo "ERROR: could not read SUPPORTED_ARCH from Makefile" >&2
    exit 1
fi

for t in ${TARGETS}; do
    if [ ! -f "config/${t}-camera.mk" ]; then
        echo "ERROR: camx_targets lists '${t}' but config/${t}-camera.mk is missing" >&2
        exit 1
    fi
    case " ${MAKEFILE_ARCH} " in
        *" ${t} "*) ;;
        *)  echo "ERROR: camx_targets lists '${t}' but the Makefile's SUPPORTED_ARCH does not:" >&2
            echo "       SUPPORTED_ARCH = ${MAKEFILE_ARCH}" >&2
            echo "       dkms.conf would declare a module that is never built." >&2
            exit 1 ;;
    esac
done

for a in ${MAKEFILE_ARCH}; do
    case " ${TARGETS} " in
        *" ${a} "*) ;;
        *)  echo "camx-dkms: WARNING: Makefile builds '${a}' but camx_targets does not package it" >&2 ;;
    esac
done

echo "camx-dkms: packaging targets: ${TARGETS}"

# ── DKMS source payload ───────────────────────────────────────────────────────
# Copy the driver source into the DKMS source directory while excluding
# packaging metadata, dotfiles, and build-only files. The source tree is
# rebuilt by DKMS on kernel upgrades, so packaging recipes stay out of it.
install -d %{buildroot}%{dkms_src}
tar -cf - --exclude='./.*' \
          --exclude='./*.spec' --exclude='./*.spec.notes.md' \
          --exclude=./make-source-tarball.sh --exclude=./rpm \
    . | tar -xf - -C %{buildroot}%{dkms_src}

# ── Build / clean wrappers ────────────────────────────────────────────────────
# DKMS chdir's into $dkms_tree/$module/$version/build before invoking MAKE and
# CLEAN, so these run with cwd = the source tree and take the kernel version as
# their first argument.
#
# cam_generated_h is #include'd by camera/drivers/camera_main.c and
# camera_kt/drivers/camera_main.c but is not in the source tree -- the
# top-level Makefile generates it. Because this wrapper drives kbuild directly
# (make -C <kernel> M=<src>) rather than going through that Makefile, it has to
# generate the file itself.
cat > %{buildroot}%{dkms_src}/dkms-build <<'EOF'
#!/bin/bash
# Build camera_<arch>.ko for every supported target. Invoked by DKMS as
#   ./dkms-build <kernelver> <dkms_tree> <package_name> <package_version>
set -uo pipefail

KERNEL_VER="${1}"
BUILD_DIR="$(pwd)"
KERNEL_BUILD="/lib/modules/${KERNEL_VER}/build"

if [ ! -d "${KERNEL_BUILD}" ]; then
    echo "ERROR: no kernel build tree at ${KERNEL_BUILD}" >&2
    exit 1
fi

# Compile-time provenance header, normally produced by the top-level Makefile.
{
    echo "#define CAMERA_COMPILE_TIME \"$(date)\""
    echo "#define CAMERA_COMPILE_HOST \"$(hostname)\""
    echo "#define CAMERA_CC_VERSION \"$(${CC:-gcc} --version | head -1)\""
} > "${BUILD_DIR}/cam_generated_h"

SUPPORTED_ARCH="$(sed -n 's/^[[:space:]]*SUPPORTED_ARCH[[:space:]]*=[[:space:]]*//p' \
                  "${BUILD_DIR}/Makefile" | head -1)"
if [ -z "${SUPPORTED_ARCH}" ]; then
    echo "ERROR: could not read SUPPORTED_ARCH from ${BUILD_DIR}/Makefile" >&2
    exit 1
fi

# One make per target, with failure tracked across the whole loop. Do NOT
# collapse this into the Makefile's $(foreach ...) form: that expands to a
# single ;-joined shell line whose exit status is the last command's, so
# earlier failures are reported as success.
#
# SUPPORTED_ARCH is read from the Makefile here rather than baked in from
# camx_targets. %%install has already verified that every packaged target is
# present in SUPPORTED_ARCH, so dkms.conf only declares buildable modules.
#
# No CONFIG_* is passed on the command line: config/<arch>-camera.mk sets them
# with plain := , which a command-line assignment would override for this make
# and every sub-make.
BUILD_FAILED=0
for ARCH in ${SUPPORTED_ARCH}; do
    echo "=== building camera_${ARCH}.ko for ${KERNEL_VER} ==="
    if make -j"$(nproc)" -C "${KERNEL_BUILD}" \
            M="${BUILD_DIR}" \
            CAMERA_KERNEL_ROOT="${BUILD_DIR}" \
            CAMERA_ARCH="${ARCH}" \
            INSTALL_MOD_DIR=camera \
            KCFLAGS=-Wno-error=attributes \
            modules; then
        echo "camera_${ARCH}.ko built OK"
    else
        echo "ERROR: build failed for CAMERA_ARCH=${ARCH}" >&2
        BUILD_FAILED=1
    fi
done

[ "${BUILD_FAILED}" -eq 0 ] || exit 1
EOF

cat > %{buildroot}%{dkms_src}/dkms-clean <<'EOF'
#!/bin/bash
# Invoked by DKMS as ./dkms-clean <kernelver> <dkms_tree> <name> <version>
set -uo pipefail

KERNEL_VER="${1}"
BUILD_DIR="$(pwd)"
KERNEL_BUILD="/lib/modules/${KERNEL_VER}/build"

make -C "${KERNEL_BUILD}" M="${BUILD_DIR}" clean 2>/dev/null || true
rm -f "${BUILD_DIR}/cam_generated_h"
EOF

chmod 0755 %{buildroot}%{dkms_src}/dkms-build %{buildroot}%{dkms_src}/dkms-clean

# ── dkms.conf ─────────────────────────────────────────────────────────────────
# RPM has no external DKMS generator in this build flow, so the complete
# dkms.conf is generated here, including the package version and module table.
cat > %{buildroot}%{dkms_src}/dkms.conf <<'EOF'
PACKAGE_NAME="camx"
PACKAGE_VERSION="%{version}"

MAKE="./dkms-build ${kernelver} ${dkms_tree} ${PACKAGE_NAME} ${PACKAGE_VERSION}"
CLEAN="./dkms-clean ${kernelver} ${dkms_tree} ${PACKAGE_NAME} ${PACKAGE_VERSION}"
AUTOINSTALL="yes"

BUILD_EXCLUSIVE_CONFIG="CONFIG_ARCH_QCOM"
BUILD_EXCLUSIVE_KERNEL_MIN="6.16"
EOF

# One BUILT_MODULE_NAME / _LOCATION / DEST_MODULE_LOCATION triple per target,
# in camx_targets order.
{
    echo ""
    echo "# Packaged targets (camx_targets): ${TARGETS}"
    i=0
    for t in ${TARGETS}; do
        echo "BUILT_MODULE_NAME[${i}]=\"camera_${t}\""
        echo "BUILT_MODULE_LOCATION[${i}]=\".\""
        echo "DEST_MODULE_LOCATION[${i}]=\"/updates/camera\""
        i=$((i + 1))
    done
} >> %{buildroot}%{dkms_src}/dkms.conf

# A dkms.conf with no module table installs nothing and reports success, which
# is exactly the failure this spec exists to avoid. Fail the build instead.
grep -q '^BUILT_MODULE_NAME\[0\]=' %{buildroot}%{dkms_src}/dkms.conf || {
    echo "ERROR: generated dkms.conf has no BUILT_MODULE_NAME[0]" >&2
    exit 1
}

# ── Kernel UAPI headers ───────────────────────────────────────────────────────
# Discovered rather than hardcoded: any <tree>/include/uapi/camera/media in the
# checkout is shipped. camera_kt is spelled camera-kodiak on disk to match what
# the UMD (camx-kodiak) includes; every other tree keeps its own name.
#
# All trees ship regardless of which targets are built: UAPI headers are
# arch-independent, total well under a megabyte, and keeping the set fixed makes
# `Provides: camx-uapi-dev` a stable contract instead of one that changes shape
# with the target list.
#
# These are the raw UAPI headers. The Makefile also has a headers_install target
# that sanitizes headers, but this RPM ships the source UAPI files directly.
found_hdrs=0
for hdr_dir in */include/uapi/camera/media; do
    [ -d "${hdr_dir}" ] || continue
    tree="${hdr_dir%%/include/uapi/camera/media}"
    case "${tree}" in
        camera_kt) dest=camera-kodiak ;;
        *)         dest="${tree}" ;;
    esac
    install -d %{buildroot}%{_includedir}/camx/${dest}/media
    install -m 0644 "${hdr_dir}"/*.h %{buildroot}%{_includedir}/camx/${dest}/media/
    echo "camx-dkms: headers ${hdr_dir} -> %{_includedir}/camx/${dest}/media"
    found_hdrs=$((found_hdrs + 1))
done
if [ "${found_hdrs}" -eq 0 ]; then
    echo "ERROR: no */include/uapi/camera/media tree found -- layout changed?" >&2
    exit 1
fi

%post
# Register the source tree, then build and install for every kernel whose
# headers are present. See header comment item 3 for why this is not
# $(uname -r): in a KIWI image chroot uname -r is the build runner's kernel.
dkms add -m %{mod_name} -v %{version} --rpm_safe_upgrade >/dev/null 2>&1 || :

built=0
for kdir in %{_usrsrc}/kernels/*; do
    [ -d "${kdir}" ] || continue
    kver=$(basename "${kdir}")
    if dkms build   -m %{mod_name} -v %{version} -k "${kver}" &&
       dkms install -m %{mod_name} -v %{version} -k "${kver}" --force; then
        built=$((built + 1))
    else
        echo "camx-dkms: WARNING: DKMS build failed for kernel ${kver}" >&2
    fi
done

if [ "${built}" -eq 0 ]; then
    cat >&2 <<'WARN'
camx-dkms: WARNING: no camera module was built.
  No kernel headers were found under /usr/src/kernels/, or every build failed.
  Install the matching kernel-devel and run, per kernel version:
      dkms build   -m camx -v %{version} -k <kernel-version>
      dkms install -m camx -v %{version} -k <kernel-version> --force
WARN
fi
# Never fail the transaction: the source payload is installed correctly either
# way, and a failed module build must not abort an image assembly.
exit 0

%preun
# $1 == 0 is uninstall; on upgrade DKMS handles the version transition itself.
if [ "$1" = "0" ]; then
    dkms remove -m %{mod_name} -v %{version} --all --rpm_safe_upgrade || :
fi
exit 0

%files
%license LICENSE.txt
%doc SECURITY.md
%{dkms_src}/

%files -n camx-linux-devel
%license LICENSE.txt
%{_includedir}/camx/

%changelog
* Wed Aug 26 2026 Kripalsinh Rana <kripalsi@qti.qualcomm.com> - 1.0.5-1
- Initial RPM packaging of camera-driver 1.0.5 as DKMS source.

# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause

%global debug_package %{nil}
%global _build_id_links none

%global mod_name  camx
%global dkms_src  %{_usrsrc}/%{mod_name}-%{version}
%global upstream_name camera-driver

%global camx_targets qcm6490 qcs9100 qcs615 x1e80100

Name:           camx-dkms
Version:        1.0.5
Release:        2%{?dist}
Summary:        Qualcomm CamX camera kernel driver (DKMS source)

License:        GPL-2.0-only
URL:            https://github.com/qualcomm-linux/camera-driver

Source0:        %{url}/archive/refs/tags/v%{version}.tar.gz#/%{upstream_name}-%{version}.tar.gz
Source1:        camx-dkms.build
Source2:        camx-dkms.clean
Source3:        camx-dkms.dkms

ExclusiveArch:  aarch64

Requires:       epel-release
Requires:       dkms >= 2.8
Requires:       gcc
Requires:       make

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
# DKMS builds modules on the target; rpmbuild only stages source, scripts, and headers.

%install
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

install -d %{buildroot}%{dkms_src}
tar -cf - --exclude='./.*' \
          --exclude='./*.spec' --exclude='./*.spec.notes.md' \
          --exclude=./make-source-tarball.sh --exclude=./rpm \
    . | tar -xf - -C %{buildroot}%{dkms_src}

install -Dm0755 %{SOURCE1} %{buildroot}%{dkms_src}/dkms-build
install -Dm0755 %{SOURCE2} %{buildroot}%{dkms_src}/dkms-clean

sed 's/#MODULE_VERSION#/%{version}/' %{SOURCE3} > %{buildroot}%{dkms_src}/dkms.conf

{
    echo ""
    i=0
    for t in ${TARGETS}; do
        echo "BUILT_MODULE_NAME[${i}]=\"camera_${t}\""
        echo "BUILT_MODULE_LOCATION[${i}]=\".\""
        echo "DEST_MODULE_LOCATION[${i}]=\"/updates/camera\""
        i=$((i + 1))
    done
} >> %{buildroot}%{dkms_src}/dkms.conf

grep -q '^BUILT_MODULE_NAME\[0\]=' %{buildroot}%{dkms_src}/dkms.conf || {
    echo "ERROR: generated dkms.conf has no BUILT_MODULE_NAME[0]" >&2
    exit 1
}

# Collect UAPI headers from all trees and install camera_kt as camera-kodiak.
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
exit 0

%preun
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
* Wed Sep 23 2026 Gangabhavani Yenugula <gyenugul@qti.qualcomm.com> - 1.0.5-2
- Extract the inline dkms-build/dkms-clean/dkms.conf heredocs into standalone
  camx-dkms.build, camx-dkms.clean and camx-dkms.dkms Source file

* Wed Aug 26 2026 Kripalsinh Rana <kripalsi@qti.qualcomm.com> - 1.0.5-1
- Initial RPM packaging of camera-driver 1.0.5 as DKMS source.

# pkg-rpm-camx-dkms

RPM packaging for the Qualcomm CamX camera kernel driver on CentOS Stream 10.
The package is built from the upstream
[camera-driver](https://github.com/qualcomm-linux/camera-driver) source and
uses DKMS to build camera kernel modules on the target system.

## About the CamX Driver

The CamX driver provides the kernel-side camera stack for Qualcomm platforms,
including:

- Spectra ISP and IFE, BPS, IPE, ICP, JPEG, and LRME camera blocks.
- Sensor, flash, actuator, OIS, I2C, and CCI support.
- V4L2 and media-controller integration.
- Camera buffer, power, bandwidth, and CRM synchronization support.

The RPM currently packages these camera targets:

```text
qcm6490 qcs9100 qcs615 x1e80100
```

DKMS builds one module per target, named `camera_<target>.ko`, against the
kernel headers installed on the device. Modules are installed under the
kernel's `updates/camera` directory and are rebuilt when a supported kernel is
updated.

## Repository Layout

The `c10s` branch contains the RPM packaging files:

| File | Purpose |
|---|---|
| `camx-dkms.spec` | Builds the DKMS source package and `camx-linux-devel` subpackage. |
| `sources` | SHA-512 checksum for the upstream source archive. |
| `README.md` | Package and repository documentation. |
| `LICENSE.txt` | License for the RPM packaging repository. |

The source archive is not committed to this repository. The spec file's
`Source0` points to the upstream release, and the checksum in `sources` is
verified before the RPM is built.

## Packages

### `camx-dkms`

Contains the CamX source and DKMS metadata under:

```text
/usr/src/camx-<version>/
```

The package does not compile the kernel module during RPM creation. The module
is built by DKMS when the package is installed or when a compatible kernel is
added.

### `camx-linux-devel`

Contains CamX kernel UAPI headers under:

```text
/usr/include/camx/
```

This package contains headers only; it does not build or load a kernel module.
The headers are used by proprietary camera userspace components during
compilation and are not required for normal camera runtime operation.

## Installation

Install the runtime DKMS package on the target device:

```bash
sudo dnf install camx-dkms
```


## CI Workflows

The GitHub Actions workflows use the shared
[`qcom-rpm-utils`](https://github.com/qualcomm-linux/qcom-rpm-utils) build
environment:

| Workflow | Trigger | Purpose |
|---|---|---|
| `build-on-pr.yml` | Pull request | Downloads and verifies the source, then builds the RPM. |
| `pkg-release.yml` | Manual dispatch | Builds and publishes the RPM to Artifactory after approval. |

Pull requests for the CentOS Stream 10 package must target the `c10s` branch.
The build uses the source filename and checksum recorded in `sources`.

## Updating the Package Version

1. Update `Version:` and the upstream `Source0` reference in `camx-dkms.spec`.
2. Download the matching upstream source archive.
3. Regenerate `sources` using:

   ```bash
   sha512sum --tag camera-driver-<version>.tar.gz > sources
   ```

4. Commit the spec and `sources`, then open a pull request against `c10s`.
5. After the pull request is merged, run `pkg-release.yml` to publish the RPM.

The source archive is fetched from the lookaside cache when available. On a
cache miss, the workflow fetches it from `Source0`, verifies the SHA-512
checksum, and caches it during release.

## Contact

For packaging or build issues, contact the Qualcomm Linux camera package
maintainers through the repository issue tracker or the project review process.

## License

The RPM packaging files in this repository are licensed under the BSD-3-Clause
license; see [`LICENSE.txt`](LICENSE.txt).

The upstream CamX camera driver is licensed separately under GPL-2.0-only, as
declared by `camx-dkms.spec`.

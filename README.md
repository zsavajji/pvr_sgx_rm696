# pvr_sgx_rm696: the Nokia N9's SGX driver on Linux 6.18

The PowerVR SGX 530 kernel driver for the Nokia N9 (RM-696) on Linux 6.18. It keeps the interface of
Harmattan PR1.3's closed GPU libraries (SGX DDK **1.4.14.2514**, `*_r125.so`, `libsrv_um`), so
Harmattan's own X server, compositor and GLES2 apps run on a current kernel, unchanged.

It builds two kernel modules:

- `pvrsrvkm.ko`: the services and the SGX itself (`/dev/pvrsrvkm`);
- `omaplfb.ko`: the display class on `/dev/fb0`, over omapfb.

## What you need

- **The kernel**, [`linux_mainline_rm696`](https://github.com/zsavajji/linux_mainline_rm696) (branch `rm696`), configured and built:
  the driver links against its `Module.symvers` and needs what it exports (`registered_fb`, Nokia's DSS
  notifier).
- **An ARM cross compiler** on Linux (`arm-linux-gnueabihf-`, Debian's `gcc-arm-linux-gnueabihf`). A
  kernel and its modules don't build on macOS.
- **On the phone**, nothing to install: Harmattan PR1.3 already carries the matching GPU libraries.

## Building

The usual way is the build kit, [`rm696_mainline_port`](https://github.com/zsavajji/rm696_mainline_port) (documentation:
https://zsavajji.github.io/rm696_mainline_port/), with the three repositories side by side:

```sh
git clone https://github.com/zsavajji/rm696_mainline_port
git clone --depth 1 --branch rm696 https://github.com/zsavajji/linux_mainline_rm696
git clone https://github.com/zsavajji/pvr_sgx_rm696
cd rm696_mainline_port
RELEASE=1 kernel/build.sh      # kernel, this driver (PVR=../pvr_sgx_rm696) and the bootable image
```

By hand, against a kernel you have already built:

```sh
make -C <kernel source> O=<kernel build dir> ARCH=arm CROSS_COMPILE=arm-linux-gnueabihf- \
  M=$PWD modules               # -> pvrsrvkm.ko, omaplfb.ko
```

`Kbuild` sets Harmattan's build options (release, EDM trace, command trace); a compile-time check
refuses any other set (`0x2d001c`), because the closed libraries check them at start-up.

## On the phone

The build kit puts both modules in the image's `/lib/modules/<version>/extra/`. Harmattan's own
`/etc/init/sgx.conf` loads them as on stock (`modprobe omaplfb` brings `pvrsrvkm` with it) and then runs
its `pvrsrvinit_r125`. `cat /proc/pvr/version` shows the driver's DDK version once it's up.

| Module parameter | Default | Meaning |
|---|---|---|
| `pvrsrvkm.cpu_min_khz` | `800000` | while the SGX is busy the CPU stays at or above this frequency (kHz); `0` turns it off |

The SGX runs at 195.2 MHz and powers down 1 ms after it idles, as Nokia's driver did.

## Licence

GPL-2.0 (`COPYING`), as Imagination Technologies and Nokia released it. `README` is Imagination's
original notice.

## Where it comes from

This is Nokia's in-tree `drivers/gpu/pvr` from the N900 kernel, as forward-ported to 5.0 by Maemo Leste:
[maemo-leste/n9xx-linux](https://github.com/maemo-leste/n9xx-linux) branch `pvr-wip-5.0.y` at c46b37b
(plus `include/video/sgx-util.h`). It is the same DDK build as Harmattan's module: 495 of that
module's 497 function names exist in it.

Changes from that 5.0 port:
- **Probe from the device tree** (`ti,omap3630-gpu`, the gpu node 6.18's omap36xx.dtsi already has)
  instead of a self-registered platform device. The IRQ comes from `platform_get_irq`: the 5.0 port's
  hardcoded `NR_IRQS + 21` isn't a valid IRQ number on a DT kernel.
- **Power by runtime PM**: the SGX sits in a `ti-sysc` target module that owns its clocks. The module's
  `fck` is still used, but only to set and read the rate (200 MHz for r125).
- **Flip events work**: the 5.0 port's omapfb patch never set the overlay notify hook, so every flip or
  update wait from userspace got `-ENOSYS`. The kernel implements the overlay events, mapping Nokia's
  `in_use` to apply.c's `updating`, and bounds-checks the overlay id.
- **Event timestamps**: `tv_usec` was `tv_nsec * 1000` (should divide), in flip/sync events and hwrec dumps.
- omaplfb: the two framebuffer notifiers are gone (6.18 has no mode change or blank events). The blank
  flag they set was never read, and the N9's framebuffer mode never changes.
- 6.18 API updates: `proc_ops`, `pde_data`, `FOP_UNSIGNED_OFFSET`, `vm_flags_set`, `mmap_read_lock`,
  `get_user_pages` without vmas, `follow_pfnmap_start` (the page-table walk isn't possible from modules
  anymore), `ioremap`/`ioremap_cache`, a vmap-based `vmalloc` with page protection (`__vmalloc` lost that
  argument), `timer_container_of`/`timer_delete`, `strscpy`, `DEFINE_SEMAPHORE(x, 1)`, no `no_llseek`.
- **Wrapped PFN mappings** (`OSAcquirePhysPageAddr()` in `osfunc.c`): memory without a struct page
  (omapfb's VRAM, reserved above lowmem) took its physical address from `vm_pgoff`, which 6.18's
  `remap_pfn_range()` sets only for private mappings: EGL images of framebuffer memory (gltexturesink, the
  camera viewfinder) pointed the SGX at physical 0 (L3 in-band errors, a BUG). The PFNs now come from the
  page tables.
- **A CPU floor while the GPU works** (`sysutils.c`, module parameter `cpu_min_khz`, default 800000, 0 =
  off): while the SGX is busy the CPU stays at or above that frequency.

## Checking the interface: check-abi.py

`check-abi.py [ours.ko] [harmattan.ko]` compares, without the phone, how this `pvrsrvkm.ko` and
Harmattan's own dispatch ioctls (its header says how to extract Harmattan's module from the firmware's
root filesystem; it needs `llvm-objdump`).

Harmattan's `pvrsrvkm.ko` (built with GCC 4.4) and ours (GCC 14) both inline every ioctl handler into
one switch. Both map ioctl numbers to the same indices (constants `0xc01c6700`/`0x3fe39900`) and
range-check index ≤ 105. They leave the same 11 indices unhandled and send the same 24 indices to one
shared handler. In every handler where both builds have a distinctive kernel call, it is the same one
(59 of 59). A swap of two handlers would be caught in 2121 of the 2145 possible pairs. This covers
the dispatch, not the layout of each ioctl's argument structs. Those come from the same DDK headers,
and on the phone a mismatch shows up at SGX init or on the first GL call.

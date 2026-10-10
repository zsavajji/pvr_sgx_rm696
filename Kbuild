# SGX DDK 1.4.14.2514 kernel side, built as an external module (kernel/build.sh).
# Options as Harmattan's pvrsrvkm.ko: release, EDM trace, command trace.
obj-m := pvrsrvkm.o omaplfb.o

omaplfb-y := omaplfb_displayclass.o omaplfb_linux.o

pvrsrvkm-y := osfunc.o mmap.o module.o proc.o pvr_bridge_k.o mm.o event.o \
	buffer_manager.o devicemem.o deviceclass.o handle.o hash.o pvrsrv.o queue.o ra.o \
	resman.o power.o mem.o bridged_pvr_bridge.o sgxinit.o sgxreset.o sgxutils.o sgxkick.o \
	sgxtransfer.o mmu.o pb.o perproc.o sysconfig.o sysutils.o osperproc.o bridged_support.o \
	bridged_sgx_bridge.o sgxpower.o pvr_events.o pvr_debugfs.o pvr_trace_cmd.o

ccflags-y := -DCONFIG_PVR_RELEASE -DCONFIG_PVR_EDM_DEBUG -DCONFIG_PVR_TRACE_CMD \
	-DCONFIG_PVR_TRACE_CMD_BUF_SHIFT=3 -DPVR_BUILD_DIR=\"\" -DPVR_BUILD_DATE=\"\" \
	-include $(src)/pvrconfig.h

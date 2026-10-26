# ╔══════════════════════════════════════════════════════════════════════════╗
# ║  mythix-system-manager  •  Makefile                                      ║
# ║  Installs / uninstalls Mythix System Manager, desktop entry & Polkit     ║
# ╚══════════════════════════════════════════════════════════════════════════╝

PREFIX      ?= /usr/local
BINDIR      := $(PREFIX)/bin
LIBDIR      := $(PREFIX)/lib/mythix-system-manager
APPDIR      := /usr/share/applications
POLICYDIR   := /usr/share/polkit-1/actions

.PHONY: all install uninstall test check

all: check

check:
	python3 -m py_compile mythix-system-manager.py system_manager/*.py system_manager/pages/*.py

test: check
	python3 -m unittest discover -s tests -v

install:
	install -d "$(DESTDIR)$(BINDIR)"
	install -d "$(DESTDIR)$(LIBDIR)/system_manager/pages"
	install -d "$(DESTDIR)$(APPDIR)"
	install -d "$(DESTDIR)$(POLICYDIR)"
	install -m 0755 mythix-system-manager.py "$(DESTDIR)$(LIBDIR)/mythix-system-manager.py"
	install -m 0644 system_manager/*.py "$(DESTDIR)$(LIBDIR)/system_manager/"
	install -m 0644 system_manager/pages/*.py "$(DESTDIR)$(LIBDIR)/system_manager/pages/"
	ln -sf "$(LIBDIR)/mythix-system-manager.py" "$(DESTDIR)$(BINDIR)/mythix-system-manager"
	install -m 0644 data/com.mythix.system-manager.desktop "$(DESTDIR)$(APPDIR)/com.mythix.system-manager.desktop"
	install -m 0644 data/com.mythix.system-manager.policy "$(DESTDIR)$(POLICYDIR)/com.mythix.system-manager.policy"

uninstall:
	rm -f "$(DESTDIR)$(BINDIR)/mythix-system-manager"
	rm -rf "$(DESTDIR)$(LIBDIR)"
	rm -f "$(DESTDIR)$(APPDIR)/com.mythix.system-manager.desktop"
	rm -f "$(DESTDIR)$(POLICYDIR)/com.mythix.system-manager.policy"

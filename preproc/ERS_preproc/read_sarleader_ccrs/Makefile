include ../../../config.mk
PROG =  read_sarleader_ccrs
CSRCS = read_sarleader_ccrs.c make_prm_ccrs.c

OBJS =  $(CSRCS:.c=.o)

LIBS = -lm

$(PROG): $(OBJS)
	$(LINK.c) -o $@ $(OBJS) $(LIBS)

all:	$(PROG)

clean:
	$(RM) $(OBJS) tags core $(PROG)

install:
	$(INSTALL) $(PROG) $(bindir)

uninstall:
	$(RM) $(bindir)/$(PROG)

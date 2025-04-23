include ../../../config.mk
PROG =  ext_orb_lt1
CSRCS = ext_orb_lt1.c

OBJS =  $(CSRCS:.c=.o)
INCLUDES = -I../../S1A_preproc/include -I../../../gmtsar -I$(TIFF_INC)
CLIBS = -L../../../gmtsar -lgmtsar -L../../S1A_preproc/lib -lxmlC -L$(TIFF_LIB) -ltiff -lm

$(PROG): $(OBJS)
	$(CC) $(CFLAGS) $(LDFLAGS) -o $@ $(OBJS) $(CLIBS)

all:	$(PROG)

install:
	$(INSTALL) $(PROG) $(bindir)

uninstall:
	$(RM) $(bindir)/$(PROG)

clean:
	$(RM) $(OBJS) tags core $(PROG)

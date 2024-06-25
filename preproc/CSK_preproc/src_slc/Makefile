include ../../../config.mk
PROG =  make_slc_csk
CSRCS = make_slc_csk.c

OBJS =  $(CSRCS:.c=.o)
INCLUDES = -I../include -I../../../gmtsar $(GMT_INC) $(HDF5_CPPFLAGS) 
CLIBS = -L../../../gmtsar -lgmtsar -L../lib -lxmlC $(GMT_LIB) $(HDF5_LDFLAGS) $(HDF5_LIBS) -lm

$(PROG): $(OBJS)
	$(CC) $(CFLAGS) $(LDFLAGS) -o $@ $(OBJS) $(CLIBS) 

all:	$(PROG)

install:
	$(INSTALL) $(PROG) $(bindir)

uninstall:
	rm -f $(bindir)/$(PROG)

clean:
	rm -f $(OBJS) tags core $(PROG)

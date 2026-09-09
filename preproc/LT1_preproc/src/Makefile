include ../../../config.mk
PROG =  make_slc_lt1
CSRCS = make_slc_lt1.c

OBJS =  $(CSRCS:.c=.o)
INCLUDES = -I../include -I../../../gmtsar -I$(TIFF_INC) $(GMT_INC)
CLIBS = -L../../../gmtsar -lgmtsar $(GMT_LIB) -L../lib -lxmlC -L$(TIFF_LIB) -ltiff -lm

$(PROG): $(OBJS)
	$(CC) $(CFLAGS) $(LDFLAGS) -o $@ $(OBJS) $(CLIBS) 

all:	$(PROG)

install:
	$(INSTALL) $(PROG) $(bindir)

uninstall:
	rm -f $(bindir)/$(PROG)

clean:
	rm -f $(OBJS) tags core $(PROG)

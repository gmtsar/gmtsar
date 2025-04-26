# Makefile for statistical-cost network-flow algorithm for phase unwrapping 
# Curtis W. Chen
# Copyright 2002,2017 Board of Trustees, Leland Stanford Jr. University

# Specify your compiler (CC), whatever compiler flags (CFLAGS) you
# need, and the directory (BINDIR) in which the produced binary should
# be written.
#
# If you want to copy the man page and executable to a system directory, 
# specify the appropriate directories in the INSTALLDIR and MANDIR 
# variables and do 'make install' (you will probably need to be root).
#
# If you specify -D NO_CS2, the program will be compiled without the
# CS2 MCF solver module.

CC		=	cc
OPTIMFLAGS	=	-O3
DEBUGFLAGS	=	-ggdb
CFLAGS		=	-arch x86_64 $(OPTIMFLAGS) -Wall # -arch arm64 -Wuninitialized -m64 -D NO_CS2
LIBS		=	-lm 
BINDIR		=	../bin
INSTALLDIR	=	/usr/local/bin
MANDIR		=	/usr/local/man
SNAPHU		=	$(BINDIR)/snaphu
SNAPHUMAN	=	../man/man1/snaphu.1
OBJS		=	snaphu_tile.o \
			snaphu_solver.o \
			snaphu_io.o \
			snaphu_util.o \
			snaphu_cost.o \
			snaphu_cs2.o 


.PHONY:	all
all:		$(SNAPHU)

$(SNAPHU):	snaphu.c $(OBJS) snaphu.h Makefile 
		$(CC) $(CFLAGS) \
		snaphu.c \
		$(OBJS) \
		-o $(SNAPHU) \
		$(LIBS)

.PHONY:	gdebug
gdebug:		snaphu.c snaphu_tile.c snaphu_solver.c snaphu_io.c snaphu_util.c snaphu_cost.c snaphu_cs2.c snaphu.h
		$(CC) $(DEBUGFLAGS) snaphu.c snaphu_tile.c snaphu_solver.c snaphu_io.c snaphu_util.c snaphu_cost.c snaphu_cs2.c -o $(SNAPHU) $(LIBS)

install:	$(SNAPHU)
		cp $(SNAPHU) $(INSTALLDIR);
		cp $(SNAPHUMAN) $(MANDIR)/man1/

clean:
		@rm -f *.o

Clean:
		@rm -f *.o *~ #*#

clobber:
		@rm -f $(SNAPHU)

# end of Makefile

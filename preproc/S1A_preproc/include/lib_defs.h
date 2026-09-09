/* definitions for xml code */
#include"xmlC.h"
#include<stdio.h>
#include<stdint.h>
#include "../../../declspec.h"

EXTERN_MSC int space_count(char *);
EXTERN_MSC int strasign(char *, char *, int, int);
EXTERN_MSC int strlocate(char *, int, int);
EXTERN_MSC int create_child(tree *, char *, int, int, int);
EXTERN_MSC int show_tree(tree *, int, int);
EXTERN_MSC int get_tree(FILE *, tree *, int);
EXTERN_MSC int search_tree(tree *, char *, char *, int, int, int);
EXTERN_MSC int cat_nums(char *, char *);
EXTERN_MSC int str2ints(int *, char *);
EXTERN_MSC double date2MJD(int, int, int, int, int, double);
EXTERN_MSC int str_date2JD(char *, char *);
EXTERN_MSC double str2double(char *);
EXTERN_MSC int str2dbs(double *, char *);
EXTERN_MSC int null_MEM_STR();
EXTERN_MSC int assemble_trees(int, struct tree **, int, int, FILE *);
#ifndef _WIN32
int itoa(int, char *, int);
#endif

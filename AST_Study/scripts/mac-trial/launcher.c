#include <mach-o/dyld.h>
#include <limits.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

/* Finder need not supply an absolute argv[0]. Resolve our real bundle location. */
int main(int argc, char **argv) {
    char executable[PATH_MAX], canonical[PATH_MAX], script[PATH_MAX];
    uint32_t length=sizeof(executable);
    if (_NSGetExecutablePath(executable,&length)!=0 || !realpath(executable,canonical)) {
        perror("SYNESIS bundle path");return 1;
    }
    char *slash=strrchr(canonical,'/');
    if (!slash)return 1;
    *slash='\0';
    if (snprintf(script,sizeof(script),"%s/SYNESIS-launcher.sh",canonical)>=(int)sizeof(script))return 1;
    char **args=calloc((size_t)argc+2,sizeof(char*));
    if(!args)return 1;
    args[0]="/bin/bash";args[1]=script;
    for(int i=1;i<argc;i++)args[i+1]=argv[i];
    execv(args[0],args);
    perror("SYNESIS launcher");return 1;
}

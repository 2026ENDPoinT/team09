package dev.synesis.poc;

import java.io.*;
import java.nio.file.*;
import java.util.*;
import java.util.prefs.*;

/** Portable UI settings, with a one-time read of legacy OS preferences. */
public final class UserPreferences {
    private UserPreferences() {}
    public static Preferences forPackage(Class<?> type) {
        Node root=new Node(null,"",AppPaths.settings().resolve("preferences/user"));
        Preferences node=root.node(type.getPackageName().replace('.','/'));
        Path file=AppPaths.settings().resolve("preferences/user").resolve(type.getPackageName().replace('.','/')).resolve("values.properties");
        if(!Boolean.getBoolean("ast.study.standalone") && !Files.exists(file))try {
            Preferences previous=Preferences.userNodeForPackage(type);
            for(String key:previous.keys())node.put(key,previous.get(key,""));
            node.flush();
        }catch(BackingStoreException error) {throw new IllegalStateException("기존 표시 설정을 읽지 못했어요.",error);}
        return node;
    }
    private static final class Node extends AbstractPreferences {
        private final Path folder;
        private final Properties values=new Properties();
        Node(Node parent,String name,Path folder) {
            super(parent,name);this.folder=folder;
            try {syncSpi();}catch(BackingStoreException e){throw new IllegalStateException(e);}
        }
        protected void putSpi(String key,String value){values.setProperty(key,value);persist();}
        protected String getSpi(String key){return values.getProperty(key);}
        protected void removeSpi(String key){values.remove(key);persist();}
        private void persist(){try{flushSpi();}catch(BackingStoreException e){throw new IllegalStateException(e);}}
        protected void removeNodeSpi() throws BackingStoreException {
            try{Files.deleteIfExists(folder.resolve("values.properties"));Files.deleteIfExists(folder);}
            catch(IOException e){throw new BackingStoreException(e);}
        }
        protected String[] keysSpi(){return values.stringPropertyNames().toArray(String[]::new);}
        protected String[] childrenNamesSpi() throws BackingStoreException {
            if(!Files.isDirectory(folder))return new String[0];
            try(var files=Files.list(folder)){return files.filter(Files::isDirectory).map(p->p.getFileName().toString()).toArray(String[]::new);}
            catch(IOException e){throw new BackingStoreException(e);}
        }
        protected AbstractPreferences childSpi(String name){return new Node(this,name,folder.resolve(name));}
        protected void syncSpi() throws BackingStoreException {
            Path file=folder.resolve("values.properties");if(!Files.exists(file))return;
            try(var in=Files.newInputStream(file)){values.clear();values.load(in);}catch(IOException e){throw new BackingStoreException(e);}
        }
        protected void flushSpi() throws BackingStoreException {
            try{
                Files.createDirectories(folder);Path temp=Files.createTempFile(folder,"preferences-",".tmp");
                try{
                    try(var out=Files.newOutputStream(temp)){values.store(out,"SYNESIS user settings");}
                    try{Files.move(temp,folder.resolve("values.properties"),StandardCopyOption.ATOMIC_MOVE,StandardCopyOption.REPLACE_EXISTING);}
                    catch(AtomicMoveNotSupportedException e){Files.move(temp,folder.resolve("values.properties"),StandardCopyOption.REPLACE_EXISTING);}
                }finally{Files.deleteIfExists(temp);}
            }catch(IOException e){throw new BackingStoreException(e);}
        }
    }
}

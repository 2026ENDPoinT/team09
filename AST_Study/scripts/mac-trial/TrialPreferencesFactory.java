package dev.synesis.trial;

import java.io.*;
import java.nio.file.*;
import java.util.*;
import java.util.prefs.*;

/** Keeps trial UI preferences beside trial data instead of the developer's macOS preferences. */
public final class TrialPreferencesFactory implements PreferencesFactory {
    private final Preferences user=new Node(null,"",Path.of(".synesis","preferences","user"));
    private final Preferences system=new Node(null,"",Path.of(".synesis","preferences","system"));
    public Preferences userRoot() {return user;}
    public Preferences systemRoot() {return system;}
    private static final class Node extends AbstractPreferences {
        private final Path folder;
        private final Properties values=new Properties();
        Node(Node parent,String name,Path folder) {
            super(parent,name);this.folder=folder;
            try {syncSpi();} catch(BackingStoreException error) {throw new IllegalStateException(error);}
        }
        protected void putSpi(String key,String value) {values.setProperty(key,value);persist();}
        protected String getSpi(String key) {return values.getProperty(key);}
        protected void removeSpi(String key) {values.remove(key);persist();}
        private void persist() {try {flushSpi();} catch(BackingStoreException error) {throw new IllegalStateException(error);}}
        protected void removeNodeSpi() throws BackingStoreException {
            try {Files.deleteIfExists(folder.resolve("values.properties"));Files.deleteIfExists(folder);}
            catch(IOException error) {throw new BackingStoreException(error);}
        }
        protected String[] keysSpi() {return values.stringPropertyNames().toArray(String[]::new);}
        protected String[] childrenNamesSpi() throws BackingStoreException {
            if(!Files.isDirectory(folder))return new String[0];
            try(var children=Files.list(folder)) {
                return children.filter(Files::isDirectory).map(p->p.getFileName().toString()).toArray(String[]::new);
            } catch(IOException error) {throw new BackingStoreException(error);}
        }
        protected AbstractPreferences childSpi(String name) {return new Node(this,name,folder.resolve(name));}
        protected void syncSpi() throws BackingStoreException {
            Path file=folder.resolve("values.properties");
            if(!Files.exists(file))return;
            try(var input=Files.newInputStream(file)) {values.clear();values.load(input);}
            catch(IOException error) {throw new BackingStoreException(error);}
        }
        protected void flushSpi() throws BackingStoreException {
            try {
                Files.createDirectories(folder);
                Path temp=Files.createTempFile(folder,"preferences-",".tmp");
                try {
                    try(var output=Files.newOutputStream(temp)) {values.store(output,"SYNESIS trial preferences");}
                    Files.move(temp,folder.resolve("values.properties"),StandardCopyOption.REPLACE_EXISTING);
                } finally {Files.deleteIfExists(temp);}
            } catch(IOException error) {throw new BackingStoreException(error);}
        }
    }
}

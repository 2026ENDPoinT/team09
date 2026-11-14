package dev.synesis.poc.ui;

import javax.imageio.ImageIO;
import javax.swing.Icon;
import java.awt.Component;
import java.awt.Graphics;
import java.awt.Graphics2D;
import java.awt.RenderingHints;
import java.awt.image.BufferedImage;
import java.io.IOException;

/** Figma's SYNESIS — Uppercase / Solid master, shared by every in-app header. */
public final class BrandLogo {
    private static final BufferedImage WORDMARK = loadWordmark();
    private static final java.util.Map<Integer,Icon> ICONS=new java.util.LinkedHashMap<>(32,.75f,true) {
        @Override protected boolean removeEldestEntry(java.util.Map.Entry<Integer,Icon> eldest){return size()>32;}
    };

    private BrandLogo() {}

    private static BufferedImage loadWordmark() {
        try (var input = BrandLogo.class.getResourceAsStream("/dev/synesis/poc/branding/uppercase-solid-master.png")) {
            if (input == null) throw new IllegalStateException("Missing SYNESIS wordmark");
            BufferedImage image = ImageIO.read(input);
            if (image == null) throw new IllegalStateException("Invalid SYNESIS wordmark");
            return image;
        } catch (IOException exception) {
            throw new IllegalStateException("Cannot read SYNESIS wordmark", exception);
        }
    }

    public static synchronized Icon wordmark(int width) {
        return ICONS.computeIfAbsent(Math.max(1,width),w->new DeviceImageIcon(WORDMARK,w,
            Math.max(1,(int)Math.round(w*(double)WORDMARK.getHeight()/WORDMARK.getWidth()))));
    }
}

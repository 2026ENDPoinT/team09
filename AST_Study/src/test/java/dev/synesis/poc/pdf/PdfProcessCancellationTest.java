package dev.synesis.poc.pdf;

import dev.synesis.poc.PythonRuntime;
import java.nio.file.*;
import java.time.Duration;
import java.util.*;
import java.util.concurrent.TimeUnit;

/** Actual child processes and stdin; no API requests, credentials, or GUI. */
public final class PdfProcessCancellationTest {
    public static void main(String[] args) throws Exception {
        Path dir=Files.createTempDirectory("synesis-cancel-fixture-");
        try {
            Path receipt=dir.resolve("stopped.json");
            Process child=python("import sys,json,time;from pathlib import Path;v=json.loads(sys.stdin.readline());assert v=={'command':'cancel'};time.sleep(.15);Path(sys.argv[1]).write_text('stopped')",receipt.toString());
            long start=System.nanoTime();
            PdfProcess.cancelProcess(child,true,Duration.ofSeconds(3));
            check((System.nanoTime()-start)/1_000_000<500,"Cancellation blocked the UI caller");
            check(child.waitFor(4,TimeUnit.SECONDS),"Cooperative worker was abandoned");
            check(child.exitValue()==0 && Files.readString(receipt).equals("stopped"),"Worker was killed before saving its stop receipt");
            Process local=python("import time;time.sleep(30)");
            PdfProcess.cancelProcess(local,false,Duration.ofSeconds(3));
            check(local.waitFor(2,TimeUnit.SECONDS),"Unmanaged local process survived cancellation");
            Process stuck=python("import time;time.sleep(30)");
            PdfProcess.cancelProcess(stuck,true,Duration.ofMillis(100));
            check(stuck.waitFor(2,TimeUnit.SECONDS),"Unresponsive worker exceeded bounded cleanup");
            System.out.println("PASS: cooperative stop saves receipt, caller stays responsive, stuck/local workers are bounded.");
        } finally {
            try(var paths=Files.walk(dir)){for(Path p:paths.sorted(Comparator.reverseOrder()).toList())Files.deleteIfExists(p);}
        }
    }
    private static Process python(String script,String...args)throws Exception {
        var command=new ArrayList<>(List.of(PythonRuntime.pdf(),"-u","-c",script));command.addAll(List.of(args));
        return new ProcessBuilder(command).redirectError(ProcessBuilder.Redirect.INHERIT).start();
    }
    private static void check(boolean value,String message){if(!value)throw new AssertionError(message);}
}

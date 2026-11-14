package dev.synesis.poc.pdf;

import com.google.gson.*;
import dev.synesis.poc.PythonRuntime;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.util.*;
import java.util.concurrent.ConcurrentHashMap;
import java.util.function.Consumer;
import java.util.function.Function;

/** Dedicated PDF subprocesses; local extraction never loads .env. Opt-in AI reads its key itself. */
final class PdfProcess implements AutoCloseable {
    static final class UnreportedFailure extends IOException {
        UnreportedFailure(int exitCode, String stderr) {
            super("PDF 작업 프로세스가 비정상 종료됐습니다 (종료 코드 " + exitCode +
                stderrKind(stderr) + "). 다시 시도해 주세요.");
        }
    }

    private static String stderrKind(String stderr) {
        if (stderr.contains("Fatal Python error")) return ", Python 런타임 오류";
        var matcher = java.util.regex.Pattern.compile("(?m)^([A-Za-z_][A-Za-z0-9_]*(?:Error|Exception))(?::|$)").matcher(stderr);
        String kind = null;
        while (matcher.find()) kind = matcher.group(1);
        return kind == null ? "" : ", " + kind;
    }

    static boolean economyRuntime(String script,List<String> arguments) throws IOException {
        return generationRuntime(script,arguments)!=null;
    }

    static String generationRuntime(String script,List<String> arguments) throws IOException {
        if(!script.equals("pdf_ai.py") || arguments.isEmpty()
                || !Set.of("generate","recover","vision-region","vision-plan","group-plan","prepare-study","vision-auto").contains(arguments.getFirst()))return null;
        int at=arguments.indexOf("--request");
        if(at<0 || at+1>=arguments.size())return null;
        try {
            JsonObject request=JsonParser.parseString(Files.readString(Path.of(arguments.get(at+1)))).getAsJsonObject();
            String strategy=request.has("strategy")?request.get("strategy").getAsString():"";
            return switch(strategy){
                case "newest-k1-2-1" -> "pdf_k121_entry.py";
                case "newest-k1-2-2" -> "pdf_k122_entry.py";
                case "newest-k1-2-3" -> "pdf_k123_entry.py";
                case "newest-k1-2-4" -> "pdf_k124_entry.py";
                case "newest-k1-2-5" -> "pdf_k125_entry.py";
                default -> null;
            };
        }catch(JsonParseException | IllegalStateException malformed){throw new IOException("생성 엔진 설정을 읽을 수 없어요.",malformed);}
    }

    private final Set<Process> processes = ConcurrentHashMap.newKeySet();
    private final Set<Process> controlledProcesses = ConcurrentHashMap.newKeySet();
    private final Set<Process> cancellingProcesses = ConcurrentHashMap.newKeySet();
    private volatile boolean closed;
    private int revision;
    synchronized int ticket() { return revision; }
    void run(String script, List<String> arguments, int ticket, Consumer<JsonObject> events) throws Exception {
        run(script,arguments,ticket,events,null);
    }
    void run(String script,List<String> arguments,int ticket,Consumer<JsonObject> events,Function<JsonObject,JsonObject> local) throws Exception {
        run(script,arguments,ticket,events,local,null);
    }
    void run(String script,List<String> arguments,int ticket,Consumer<JsonObject> events,Function<JsonObject,JsonObject> local,ChatReplyControl reply) throws Exception {
        if(reply!=null){
            int at=arguments.indexOf("--request");
            if(at<0)throw new IllegalArgumentException("답변 요청 경로가 없어요.");
            Path request=Path.of(arguments.get(at+1));
            reply.prepare(request.resolveSibling(request.getFileName().toString().replace(".json",".result.json")));
        }
        if(local!=null&&!script.equals("home_assistant.py"))throw new IllegalArgumentException("비서 전용 연결이에요.");
        if(!Boolean.getBoolean("ast.study.standalone") && script.equals("pdf_ai.py")
                && (arguments.contains("--allow-remote") || !arguments.isEmpty() && arguments.getFirst().equals("tutor"))) {
            int folderAt=arguments.indexOf("--folder"),requestAt=arguments.indexOf("--request");
            if(folderAt<0 || requestAt<0)throw new IOException("크레딧 장부에 필요한 실행 경로가 없어요.");
            Path folder=Path.of(arguments.get(folderAt+1));Path library=folder.getParent();
            SubscriptionUsage.activate(library);
            Path requestPath=Path.of(arguments.get(requestAt+1));
            JsonObject request=JsonParser.parseString(Files.readString(requestPath)).getAsJsonObject();
            request.addProperty("creditBilling",true);
            Files.writeString(requestPath,new Gson().toJson(request));
        }
        String runtime=generationRuntime(script,arguments);
        String entryScript=runtime==null?script:runtime;
        List<String> command = new ArrayList<>(List.of(PythonRuntime.pdf(), "-u", dev.synesis.poc.AppPaths.script(entryScript).toString()));
        command.addAll(arguments);
        boolean controlled=script.equals("pdf_ai.py") && arguments.contains("--allow-remote")
            && !arguments.isEmpty() && !arguments.getFirst().equals("tutor");
        if(controlled)command.add("--control-stdin");
        ProcessBuilder builder = dev.synesis.poc.AppPaths.process(new ProcessBuilder(command));
        builder.environment().put("PYTHONUTF8", "1");
        builder.environment().put("PYTHON_DOTENV_DISABLED", "1");
        builder.environment().put("SYNESIS_LOCAL_HIERARCHY", "7");
        Process process;
        synchronized (this) {
            if (closed || ticket != revision) throw new IOException("작업이 취소되었습니다.");
            process = builder.start();
            processes.add(process);
            if(reply!=null)reply.attach(process);
            if(controlled)controlledProcesses.add(process);
        }
        String lastError = null;
        StringBuilder stderr = new StringBuilder();
        Thread stderrReader = Thread.ofVirtual().name("pdf-process-stderr").start(() -> {
            try (InputStream stream = process.getErrorStream()) {
                byte[] buffer = new byte[2048];
                int count;
                while ((count = stream.read(buffer)) != -1) {
                    stderr.append(new String(buffer, 0, count, StandardCharsets.UTF_8));
                    if (stderr.length() > 16_384) stderr.delete(0, stderr.length() - 16_384);
                }
            } catch (IOException ignored) { /* Exit code still identifies a silent worker failure. */ }
        });
        try (BufferedReader reader = new BufferedReader(new InputStreamReader(process.getInputStream(), StandardCharsets.UTF_8))) {
            String line;
            while ((line = reader.readLine()) != null) {
                try {
                    JsonObject event = JsonParser.parseString(line).getAsJsonObject();
                    if (event.has("type") && event.get("type").getAsString().equals("error")) lastError = event.get("message").getAsString();
                    if(event.has("type")&&event.get("type").getAsString().equals("assistant_local_request")) {
                        if(local==null)throw new IOException("로컬 비서 연결이 없어요.");
                        if(reply!=null)reply.check();
                        JsonObject response=local.apply(event);
                        process.getOutputStream().write((new Gson().toJson(response)+"\n").getBytes(StandardCharsets.UTF_8));
                        process.getOutputStream().flush();
                    }else events.accept(event);
                } catch (JsonParseException | IllegalStateException ignored) { /* Never echo arbitrary subprocess output. */ }
            }
            int exitCode = process.waitFor();
            stderrReader.join();
            if(reply!=null){if(reply.completed())return;reply.check();}
            if (exitCode != 0) throw lastError == null
                ? new UnreportedFailure(exitCode, stderr.toString()) : new IOException(lastError);
        } catch(Exception failure) {
            if(reply!=null){if(reply.completed())return;reply.check();}
            throw failure;
        } finally {
            if(reply!=null)reply.detach();
            if(local!=null&&process.isAlive())cancelProcess(process,false,java.time.Duration.ZERO);
            if(process.isAlive())Thread.ofVirtual().name("pdf-process-settlement").start(()->{
                try {process.waitFor();}catch(InterruptedException interrupted){Thread.currentThread().interrupt();}
                finally {removeFinishedProcess(process);}
            });
            else removeFinishedProcess(process);
        }
    }
    private synchronized void removeFinishedProcess(Process process) {
        processes.remove(process);controlledProcesses.remove(process);cancellingProcesses.remove(process);notifyAll();
    }
    /** Cancellation may drain paid work asynchronously. Do not admit another file early. */
    void afterIdle(Runnable action) {
        Thread.ofVirtual().name("pdf-study-release").start(()->{
            synchronized(this) {
                while(!processes.isEmpty())try {wait();}
                catch(InterruptedException interrupted){Thread.currentThread().interrupt();return;}
            }
            action.run();
        });
    }
    synchronized void cancel() {
        revision++;
        for (Process process : processes) {
            if(cancellingProcesses.add(process))
                cancelProcess(process,controlledProcesses.contains(process),java.time.Duration.ofSeconds(30));
        }
    }
    static void cancelProcess(Process process,boolean controlled,java.time.Duration grace) {
        if(controlled && process.isAlive()) {
            try {
                process.getOutputStream().write("{\"command\":\"cancel\"}\n".getBytes(StandardCharsets.UTF_8));
                process.getOutputStream().flush();process.getOutputStream().close();
                Thread.ofVirtual().name("pdf-worker-cleanup").start(()->{
                    try {if(process.waitFor(grace.toMillis(),java.util.concurrent.TimeUnit.MILLISECONDS))return;}
                    catch(InterruptedException interrupted){Thread.currentThread().interrupt();}
                    process.descendants().forEach(ProcessHandle::destroyForcibly);process.destroyForcibly();
                });
                return;
            } catch(IOException ignored) { /* A dead/unreachable worker still needs bounded cleanup. */ }
        }
        process.descendants().forEach(ProcessHandle::destroyForcibly);process.destroyForcibly();
    }
    @Override public synchronized void close() {
        if(closed)return;
        closed=true;
        cancel();
    }
}

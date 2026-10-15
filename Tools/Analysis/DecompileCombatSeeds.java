// Focused offline decompilation from the player's original executable.
// @category TitusInMidgar.Analysis

import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.Instruction;
import ghidra.program.model.symbol.FlowType;
import java.io.PrintWriter;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.LinkedHashSet;
import java.util.Set;

public class DecompileCombatSeeds extends GhidraScript {
    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        if (args.length < 2) {
            throw new IllegalArgumentException("Expected output file and seed addresses");
        }
        Path output = Path.of(args[0]);
        Files.createDirectories(output.getParent());
        DecompInterface decompiler = new DecompInterface();
        decompiler.openProgram(currentProgram);
        Set<Address> targets = new LinkedHashSet<>();
        Set<Address> directCalls = new LinkedHashSet<>();
        for (int index = 1; index < args.length; index++) {
            targets.add(toAddr(args[index]));
        }
        try (PrintWriter writer = new PrintWriter(Files.newBufferedWriter(output))) {
            writer.println("// Recovered pseudocode, not original source. No target execution.");
            writer.println("// Original executable was imported in place; no copied binary.");
            for (Address entry : targets) {
                Function function = prepare(entry);
                if (function == null) {
                    writer.println("// UNRESOLVED seed " + entry);
                    continue;
                }
                for (Instruction instruction : currentProgram.getListing().getInstructions(function.getBody(), true)) {
                    FlowType flow = instruction.getFlowType();
                    if (flow.isCall()) {
                        for (Address callee : instruction.getDefaultFlows()) {
                            if (currentProgram.getMemory().getBlock(callee) != null &&
                                currentProgram.getMemory().getBlock(callee).isExecute()) {
                                directCalls.add(callee);
                            }
                        }
                    }
                }
                emit(writer, decompiler, function, "selected native function; role requires confirmation");
            }
            int emitted = 0;
            for (Address callee : directCalls) {
                if (targets.contains(callee) || emitted >= 24) continue;
                Function function = prepare(callee);
                if (function != null) {
                    emit(writer, decompiler, function, "direct callee, role unconfirmed");
                    emitted++;
                }
            }
        } finally {
            decompiler.dispose();
        }
        println("Titus analysis written: " + output);
    }

    private Function prepare(Address entry) throws Exception {
        Function function = getFunctionAt(entry);
        if (function != null) return function;
        disassemble(entry);
        return createFunction(entry, null);
    }

    private void emit(PrintWriter writer, DecompInterface decompiler,
                      Function function, String role) throws Exception {
        writer.println("\n// " + role + " @ " + function.getEntryPoint());
        DecompileResults result = decompiler.decompileFunction(function, 60, monitor);
        if (result.decompileCompleted() && result.getDecompiledFunction() != null) {
            writer.println(result.getDecompiledFunction().getC());
        } else {
            writer.println("// DECOMPILE INCOMPLETE: " + result.getErrorMessage());
        }
        writer.flush();
    }
}

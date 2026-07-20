#!/usr/bin/env node

import { createHash } from "node:crypto";
import { readFile, writeFile } from "node:fs/promises";

const UPSTREAM_SHA256 = "63366510248adf3a7eddf3e793dd825404efb7df3749f4d6f8557c7fa4ca8aa0";
const PATCHED_SHA256 = "67b747b73392a012ad7af59adaef2bf1a1606a843ab75ece4ec19da981bd2138";
const artifactPath = process.argv[2];

if (!artifactPath) {
  throw new Error("usage: node patch-mv3.mjs PATH_TO_UPSTREAM_OPENCV_JS");
}

const input = await readFile(artifactPath);
const inputSha256 = createHash("sha256").update(input).digest("hex");
if (inputSha256 !== UPSTREAM_SHA256) {
  throw new Error(`refusing to patch unexpected upstream artifact: ${inputSha256}`);
}

let source = input.toString("utf8");
const replacements = [
  {
    label: "named embind wrapper",
    before: "return new Function(\"body\",\"return function \"+name+\"() {\\n\"+'    \"use strict\";'+\"    return body.apply(this, arguments);\\n\"+\"};\\n\")(body)",
    after: "var named=function(){\"use strict\";return body.apply(this,arguments)};try{Object.defineProperty(named,\"name\",{value:name})}catch(e){}return named",
  },
  {
    label: "dynamic function-pointer wrapper",
    before: "return new Function(\"dynCall\",\"rawFunction\",body)(dynCall,rawFunction)",
    after: "return function(){var values=[rawFunction];for(var i=0;i<arguments.length;++i){values.push(arguments[i])}return dynCall.apply(null,values)}",
  },
  {
    label: "embind invocation wrapper",
    before: "var invokerFunction=new_(Function,args1).apply(null,args2);return invokerFunction",
    after: "return createNamedFunction(humanName,function(){if(arguments.length!==argCount-2){throwBindingError(\"function \"+humanName+\" called with \"+arguments.length+\" arguments, expected \"+(argCount-2)+\" args!\")}var destructors=needsDestructorStack?[]:null;var wired=new Array(argCount);var callArgs=[cppTargetFunc];if(isClassMethodFunc){wired[1]=argTypes[1].toWireType(destructors,this);callArgs.push(wired[1])}for(var i=0;i<argCount-2;++i){wired[i+2]=argTypes[i+2].toWireType(destructors,arguments[i]);callArgs.push(wired[i+2])}var rv=cppInvokerFunc.apply(null,callArgs);if(needsDestructorStack){runDestructors(destructors)}else{for(var i=isClassMethodFunc?1:2;i<argTypes.length;++i){if(argTypes[i].destructorFunction!==null){argTypes[i].destructorFunction(wired[i])}}}if(returns){return argTypes[0].fromWireType(rv)}})",
  },
  {
    label: "emval method-caller wrapper",
    before: "var invokerFunction=new_(Function,params).apply(null,args);return __emval_addMethodCaller(invokerFunction)",
    after: "var invokerFunction=createNamedFunction(\"methodCaller_\"+signatureName,function(handle,name,destructors,wireArgs){var values=new Array(argCount-1);var offset=0;for(var i=0;i<argCount-1;++i){values[i]=types[i+1].readValueFromPointer(wireArgs+offset);offset+=types[i+1][\"argPackAdvance\"]}var rv=handle[name].apply(handle,values);for(var i=0;i<argCount-1;++i){if(types[i+1][\"deleteObject\"]){types[i+1].deleteObject(values[i])}}if(!retType.isVoid){return retType.toWireType(destructors,rv)}});return __emval_addMethodCaller(invokerFunction)",
  },
];

for (const replacement of replacements) {
  const first = source.indexOf(replacement.before);
  const last = source.lastIndexOf(replacement.before);
  if (first < 0 || first !== last) {
    throw new Error(`${replacement.label} patch anchor is missing or not unique`);
  }
  source = source.slice(0, first) + replacement.after + source.slice(first + replacement.before.length);
}

if (/\b(?:eval|Function)\s*\(/u.test(source) || /\bnew_\s*\(\s*Function\b/u.test(source)) {
  throw new Error("dynamic JavaScript execution remains after patching");
}
await writeFile(artifactPath, source);
const outputSha256 = createHash("sha256").update(source).digest("hex");
if (outputSha256 !== PATCHED_SHA256) {
  throw new Error(`patched artifact digest is not reproducible: ${outputSha256}`);
}
console.log(`patched ${artifactPath}: ${inputSha256} -> ${outputSha256}`);
